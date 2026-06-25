from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface

# project
from bd_topo_extractor.__about__ import __wfs_crs__, __wfs_geometry__


class WfsRequest:
    def __init__(
        self,
        project: QgsProject,
        iface: QgisInterface,
        url: str,
        data: str,
        crs: QgsCoordinateReferenceSystem,
        boundingbox: QgsRectangle,
        path: str,
        schema: str,
        geom: str,
        format: str,
        error: list,
        good: list,
    ):
        """Constructor.
        :param
        project: The current QGIS project instance
        iface: An interface instance that will be passed to this class which \
        provides the hook by which you can manipulate \
        the QGIS application at run time.
        url: The wfs url
        data: The layer to extract from the wfs service
        crs: The coordinate reference system for the output layer
        boundingbox: The bounding box used to filter \
        the data from the wfs service
        path: Ouput path to save layers
        schema: Name of the data's schema
        geom: Check if the data needs to be clipped by the extent
        format: Output layer format extension
        error: List of data not in the extent
        good: List of data extracted from the extent
        """

        self.project = project
        self.iface = iface
        self.service_url = url
        self.data = data
        self.crs = crs
        self.boundingbox = boundingbox
        self.path = path
        self.schema = schema
        self.format = format
        self.geom = geom
        self.no_data = error
        self.exported = good

        self.final_layer = None

        wfs_uri = self.build_url()
        self.add_layer(wfs_uri)

    def build_url(self):
        """
        Build the data source url to fetch features intersecting the extent
        """
        wfs_uri = QgsDataSourceUri()
        wfs_uri.setParam("url", self.service_url)
        wfs_uri.setParam("version", "auto")
        wfs_uri.setParam("typename", self.data)
        wfs_uri.setParam("table", "")
        wfs_uri.setParam("srsname", "EPSG:" + str(__wfs_crs__))
        sql = "SELECT * FROM \"{data}\" as t1 WHERE ST_Intersects(t1.{geometry_column}, ST_GeometryFromText('Polygon (({xmin} {ymin}, {xmax} {ymin}, {xmax} {ymax}, {xmin} {ymax}, {xmin} {ymin}))', {crs}))".format(  # noqa: E501
            data=self.data,
            geometry_column=str(__wfs_geometry__),
            ymin=str(self.boundingbox.yMinimum()),
            xmin=str(self.boundingbox.xMinimum()),
            ymax=str(self.boundingbox.yMaximum()),
            xmax=str(self.boundingbox.xMaximum()),
            crs=str(__wfs_crs__),
        )  # nosec B608
        wfs_uri.setSql(sql)
        return wfs_uri

    def add_layer(self, wfs_uri):
        """
        Create a layer based on the WFS request.
        If needed, the layer will be clipped with the selected extent.
        The layer is then saved to the slected format and the selected CRS.
        """
        if self.schema == "*":
            export_name = self.data.replace(":", "_")
        else:
            export_name = self.data.split(self.schema + ":")[1]
        self.wfs_layer = QgsVectorLayer(wfs_uri.uri(False), export_name, "WFS")
        # Check if the WFS request has any features
        if self.wfs_layer.featureCount() > 0:
            self.exported.append(self.data)
        else:
            # If the WFS request has no features
            # the data name is added to the no_data list.
            self.no_data.append(self.data)
