#! python3  # noqa E265

"""
    Usage from the repo root folder:

    .. code-block:: bash

        python -m unittest tests.qgis.test_batch_runner

Enchaînement des lots d'une extraction découpée, avec un faux client : aucun appel réseau, aucun
réglage QGIS ni job du compte touché (la file et le registre sont remplacés par des doubles en mémoire).
"""

from unittest import mock

from qgis.core import QgsProject
from qgis.testing import start_app, unittest

from gpf_extraction.core.exceptions import ApiRequestError
from gpf_extraction.core.models import JobStatus

start_app()

from gpf_extraction.gui import batch_runner  # noqa: E402 - après start_app()
from gpf_extraction.gui import dlg_job_monitor  # noqa: E402


class FakeClient:
    def __init__(self, refuse_first=0):
        self.executed = []
        self.refuse = refuse_first

    def execute(self, process_id, body):
        if self.refuse:
            self.refuse -= 1
            raise ApiRequestError("POST", "https://x/execution", 429, b"too-many-jobs")
        self.executed.append((process_id, body))
        return JobStatus(job_id=f"job-{len(self.executed)}", status="running")

    def get_job(self, job_id):
        return JobStatus(job_id=job_id, status="running")

    def delete_job(self, job_id):
        pass


def body(*tables):
    return {"inputs": {"relations": {t: {"attributes": ["fid"]} for t in tables}, "format": "GPKG"}}


class TestBatchRunner(unittest.TestCase):
    def setUp(self):
        self.state = None
        self.jobs = []
        self.queue = mock.patch.multiple(
            "gpf_extraction.core.job_batch.BatchQueue",
            load=mock.Mock(side_effect=lambda: self.state),
            save=mock.Mock(side_effect=self._save),
            clear=mock.Mock(side_effect=self._clear),
        )
        self.registry = mock.patch.multiple(
            "gpf_extraction.gui.batch_runner.JobRegistry",
            add_job=mock.Mock(side_effect=self.jobs.append),
        )
        self.registry_monitor = mock.patch.multiple(
            "gpf_extraction.gui.dlg_job_monitor.JobRegistry",
            update_job=mock.Mock(),
            remove_job=mock.Mock(),
            ignore_job=mock.Mock(),
        )
        for patcher in (self.queue, self.registry, self.registry_monitor):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._close_monitors)

    def _save(self, state):
        self.state = state

    def _clear(self):
        self.state = None

    def _close_monitors(self):
        for monitor in list(dlg_job_monitor._ACTIVE_MONITORS):
            monitor._timer.stop()
            monitor.close()
        for timer in list(batch_runner._RETRY_TIMERS):
            timer.stop()
        batch_runner._RETRY_TIMERS.clear()

    def make_state(self, bodies):
        return {
            "process_id": "P1",
            "title": "Produit",
            "bodies": bodies,
            "total": len(bodies),
            "options": {
                "output_dir": "C:/tmp/out",
                "gpkg_name": "zone",
                "product_name": "Produit",
                "add_to_project": False,
                "poll_interval": 3600,
                "clip_to_extent": False,
                "extent_wkt": "",
                "extent_crs": "EPSG:4326",
            },
        }

    def test_output_dir_and_name_per_batch(self):
        options = {"output_dir": "C:/tmp/out", "gpkg_name": "zone"}
        self.assertTrue(batch_runner.batch_output_dir(options, 2).replace("\\", "/").endswith("C:/tmp/out/lot2"))
        self.assertEqual(batch_runner.batch_gpkg_name(options, 2), "zone_lot2")
        self.assertEqual(batch_runner.batch_gpkg_name({"gpkg_name": ""}, 1), "")
        self.assertIn("gpf_extraction_lots", batch_runner.batch_output_dir({}, 1))

    def test_batches_run_one_after_another(self):
        client = FakeClient()
        self.state = self.make_state([body("a", "b"), body("c", "d"), body("e")])
        project = QgsProject.instance()

        # lot 1
        self.assertTrue(batch_runner.launch_next_batch(client, project))
        self.assertEqual([list(b["inputs"]["relations"]) for _, b in client.executed], [["a", "b"]])
        self.assertEqual(len(self.state["bodies"]), 2)
        self.assertEqual(self.jobs[-1].product_name, "Produit (lot 1/3)")
        self.assertTrue(self.jobs[-1].output_dir.replace("\\", "/").endswith("lot1"))
        self.assertEqual(self.jobs[-1].gpkg_name, "zone_lot1")
        self.assertEqual(self.jobs[-1].requested_tables, 2)

        # la fin du suivi du lot 1 (ici : échec) lance le lot 2, une seule fois
        monitor = dlg_job_monitor._ACTIVE_MONITORS[-1]
        monitor._on_failure()
        monitor._on_failure()  # un second appel ne relance rien
        self.assertEqual([list(b["inputs"]["relations"]) for _, b in client.executed], [["a", "b"], ["c", "d"]])
        self.assertEqual(len(self.state["bodies"]), 1)
        self.assertEqual(self.jobs[-1].product_name, "Produit (lot 2/3)")

        # lot 3 : la file est vidée une fois le dernier lot parti
        dlg_job_monitor._ACTIVE_MONITORS[-1]._on_failure()
        self.assertEqual(len(client.executed), 3)
        self.assertIsNone(self.state)
        self.assertEqual(self.jobs[-1].product_name, "Produit (lot 3/3)")

        # plus rien à lancer
        dlg_job_monitor._ACTIVE_MONITORS[-1]._on_failure()
        self.assertEqual(len(client.executed), 3)

    def test_busy_service_retries_later(self):
        client = FakeClient(refuse_first=1)
        self.state = self.make_state([body("a"), body("b")])
        self.assertTrue(batch_runner.launch_next_batch(client, QgsProject.instance()))
        self.assertEqual(client.executed, [])  # refusé (429) : rien n'est parti
        self.assertEqual(len(self.state["bodies"]), 2)  # la file est intacte
        self.assertEqual(len(batch_runner._RETRY_TIMERS), 1)  # une nouvelle tentative est programmée

    def test_other_refusal_drops_the_queue(self):
        client = FakeClient()
        client.execute = mock.Mock(side_effect=ApiRequestError("POST", "https://x", 500, b"boom"))
        self.state = self.make_state([body("a"), body("b")])
        with mock.patch.object(batch_runner.QMessageBox, "warning") as warning:
            self.assertFalse(batch_runner.launch_next_batch(client, QgsProject.instance()))
        warning.assert_called_once()
        self.assertIsNone(self.state)

    def test_cancelling_a_batch_drops_the_remaining_ones(self):
        client = FakeClient()
        self.state = self.make_state([body("a"), body("b")])
        batch_runner.launch_next_batch(client, QgsProject.instance())
        monitor = dlg_job_monitor._ACTIVE_MONITORS[-1]
        monitor._cancel_or_close()  # l'utilisateur annule le job en cours
        self.assertIsNone(self.state)
        self.assertEqual(len(client.executed), 1)

    def test_no_queue_no_launch(self):
        self.assertFalse(batch_runner.launch_next_batch(FakeClient(), QgsProject.instance()))


if __name__ == "__main__":
    unittest.main()
