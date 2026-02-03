#! python3  # noqa: E265

"""
    Main plugin dialog to launch process.
"""
# PyQGIS
from qgis.PyQt.QtWidgets import QMessageBox

from bd_topo_extractor.__about__ import __wfs_schema__

# ############################################################################
# ########## Classes ###############
# ##################################


class LogMessageDialog(QMessageBox):
    def __init__(
        self,
        total_data=None,
        error_list=None,
        good_list=None,
    ):
        """Main Dialog of the plugin, composed of 5 part :
        - header (documentation, credits and metadata)
        - extent selection (drawning tool, layer selection)
        - data selection (find and select wich data you want to extract)
        - export selection (style selection, layer format and output folder)
        - footer (valid or cancel process and loading element)
        :param
        project: The current QGIS project instance
        iface: An interface instance that will be passed to this class which \
        provides the hook by which you can manipulate the QGIS application \
        at run time.
        url: The wfs url
        manager: a QNetworkAccessManager to realize the network request
        locale: language settings of QGIS to know wich documentation open
        """
        super().__init__()
        self.setWindowTitle(self.tr("Information"))

        self.setIcon(QMessageBox.Information)

        logs = self.create_logs(
            error_list,
            good_list,
            total_data,
        )
        self.setText(
            self.tr("No data number : ")
            + str(len(error_list))
            + "\n"
            + self.tr("Data number : ")
            + str(len(good_list))
            + "\n"
            + self.tr("Total data : ")
            + str(total_data),
        )
        self.setDetailedText(logs)
        self.addButton(self.tr("Ok"), QMessageBox.AcceptRole)

    def create_logs(self, error_list, good_list, total_data):
        error_logs = ""
        for error in error_list:
            error_logs += (
                " - "
                + error.replace(str(__wfs_schema__) + ":", "")
                .replace("_", " ")
                .capitalize()
                + "\n"
            )

        good_logs = ""
        for good in good_list:
            good_logs += (
                " - "
                + good.replace(str(__wfs_schema__) + ":", "")
                .replace("_", " ")
                .capitalize()
                + "\n"
            )

        log_text = (
            self.tr("MISSING :")
            + "\n"
            + error_logs
            + "---------------"
            + "\n"
            + self.tr("EXTRACTED :")
            + "\n"
            + good_logs
        )
        return log_text
