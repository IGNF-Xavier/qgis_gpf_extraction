from PyQt5.QtWidgets import QDialog, QVBoxLayout

# project
from bd_topo_extractor.__about__ import __title__


class ResultLogger(QDialog):
    def __init__(self, parent=None, good_result=None, bad_result=None, no_result=None):
        """Constructor."""
        super().__init__(parent)
        self.setObjectName(f"{__title__}")

        self.setWindowTitle("Log des résultats")

        self.layout = QVBoxLayout()
