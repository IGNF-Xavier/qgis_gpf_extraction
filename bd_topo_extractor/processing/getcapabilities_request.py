# standard
import xml.etree.ElementTree as ET

# PyQGIS
from qgis.core import QgsRectangle

# PyQt
from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

# project
from bd_topo_extractor.__about__ import __title__, __version__


class GetCapabilitiesRequest(QObject):
    finished_dl = pyqtSignal()
    """Get multiples informations from a getcapabilities request.
    List all layers available, get the maximal extent of all the Wfs' data.
    :param
        url: The wfs url
        schema: The schema of the data in the wfs url
        manager: a QNetworkAccessManager to realize the network request
        """

    def __init__(
        self, url: str = None, schema: str = None, manager: QNetworkAccessManager = None
    ):
        super().__init__()
        self.url = url
        self.schema = schema
        self.network_manager = manager

        self._pending_downloads = 0
        self.service_layers = []
        self.max_bounding_box = QgsRectangle()

        self.download()

    @property
    def pending_downloads(self):
        return self._pending_downloads

    def download(self):
        url = QUrl(f"{self.url}?service=wfs&request=GetCapabilities")
        request = QNetworkRequest(url)
        request.setRawHeader(
            b"User-Agent",
            bytes(__title__ + "/" + __version__, encoding="utf-8"),  # noqa: E501
        )
        self.reply = self.network_manager.get(request)
        self.reply.finished.connect(self.handle_finished)
        self._pending_downloads += 1

    def handle_finished(self):
        self._pending_downloads -= 1
        if self.reply.error() != QNetworkReply.NetworkError.NoError:
            print(
                f"code: {self.reply.error()} message: {self.reply.errorString()}"  # noqa: E501
            )
        else:
            data = self.reply.readAll().data().decode()
            (
                self.service_layers,
                self.max_bounding_box,
            ) = self.list_layers(data)
        if self.pending_downloads == 0:
            self.finished_dl.emit()

    def list_layers(self, data):
        # Use xml parser to find the informations.
        max_bounding_box = QgsRectangle()
        layers = []

        root = ET.fromstring(data)
        # Get list of all layers in get capabilities
        wfs = "{http://www.opengis.net/wfs/2.0}"
        feature_type_list = root.find(wfs + "FeatureTypeList")
        # Search layer in the selected schema
        for feature_type in feature_type_list:
            layer = feature_type.find(wfs + "Name").text
            list_layer_name = layer.split(":")
            # Add layer to the list and calculate the maximum extent of the WFS
            if list_layer_name[0] == self.schema:
                list_layer_name.pop(0)
                layer_name = ":".join(list_layer_name)
                layers.append(layer_name)
                max_bounding_box = self.calculate_max_bounding_box(
                    max_bounding_box, feature_type
                )
            elif self.schema == "*":
                layers.append(layer)
                max_bounding_box = self.calculate_max_bounding_box(
                    max_bounding_box, feature_type
                )
            else:
                pass
        return layers, max_bounding_box

    def calculate_max_bounding_box(self, max_bounding_box, feature_type):
        ows = "{http://www.opengis.net/ows/1.1}"
        bbox = feature_type.find(ows + "WGS84BoundingBox")
        lower_corner = bbox.find(ows + "LowerCorner").text
        upper_corner = bbox.find(ows + "UpperCorner").text
        xmin = float(lower_corner.split(" ")[0])
        ymin = float(lower_corner.split(" ")[1])
        xmax = float(upper_corner.split(" ")[0])
        ymax = float(upper_corner.split(" ")[1])
        # If the max bounding bos is not set
        if max_bounding_box.isNull():
            max_bounding_box.setXMinimum(xmin)
            max_bounding_box.setYMinimum(ymin)
            max_bounding_box.setXMaximum(xmax)
            max_bounding_box.setYMaximum(ymax)
        # Else check if it needs to get bigger
        else:
            if max_bounding_box.xMinimum() > xmin:
                max_bounding_box.setXMinimum(xmin)
            else:
                pass
            if max_bounding_box.yMinimum() > ymin:
                max_bounding_box.setYMinimum(ymin)
            else:
                pass
            if max_bounding_box.xMaximum() < xmax:
                max_bounding_box.setXMaximum(xmax)
            else:
                pass
            if max_bounding_box.yMaximum() < ymax:
                max_bounding_box.setYMaximum(ymax)
            else:
                pass
        return max_bounding_box
