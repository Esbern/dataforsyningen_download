# This file is part of the QGIS plugin developed for the Innotech – TaskForce Interreg project.
# 
# Copyright (C) 2025 Esbern Holmes, Roskilde University
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# We encourage users to inform us about their use of this plugin for research purposes.
# Contact: holmes@ruc.dk

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingException,
    QgsVectorLayer,
    QgsMapLayer,
)
from qgis.utils import iface
from ftplib import FTP_TLS
import ssl
import os
import zipfile

class ImplicitFTP_TLS(FTP_TLS):
    """
    FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        """Return the socket."""
        return self._sock

    @sock.setter
    def sock(self, value):
        """When modifying the socket, ensure it is SSL-wrapped."""
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

class DownloadBlockFilesFromFTPS(QgsProcessingAlgorithm):
    BLOCK_TYPE = 'BLOCK_TYPE'
    ATTRIBUTE_FIELD = 'ATTRIBUTE_FIELD'
    FTP_USERNAME = 'FTP_USERNAME'
    FTP_PASSWORD = 'FTP_PASSWORD'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'
    UNPACK_ZIP = 'UNPACK_ZIP'

    BLOCK_TYPES = ['DTM', 'DSM', 'Pointclouds']

    def tr(self, string):
        """Translate method"""
        return QCoreApplication.translate('DownloadFilesFromFTPS', string)

    def initAlgorithm(self, config=None):
        """Define parameters for the script"""
        layer = iface.activeLayer()
        if layer and layer.type() == QgsMapLayer.VectorLayer:
            fields = [field.name() for field in layer.fields()]
        else:
            fields = ['[No active layer found]']

        # Block type parameter (DTM, DSM, Pointclouds)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.BLOCK_TYPE,
                self.tr('Select Block Type'),
                options=self.BLOCK_TYPES,
                optional=False
            )
        )

        # Attribute field parameter (Grid ID like 605_64)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.ATTRIBUTE_FIELD,
                self.tr('Select attribute containing grid ID'),
                options=fields,
                optional=False
            )
        )

        # FTP Username parameter
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_USERNAME,
                self.tr('FTP Username (create at https://dataforsyningen.dk/)'),
                defaultValue=''
            )
        )

        # FTP Password parameter
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_PASSWORD,
                self.tr('FTP Password (WARNING: Entered in clear text, visible in logs)'),
                defaultValue='',
                multiLine=False
            )
        )

        # Output folder parameter
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                self.tr('Select output folder')
            )
        )

        # Option to unpack zip files
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.UNPACK_ZIP,
                self.tr('Automatically unpack .zip files'),
                defaultValue=False
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Main logic for the script"""
        layer = iface.activeLayer()
        if not layer or layer.type() != QgsMapLayer.VectorLayer:
            raise QgsProcessingException("No active vector layer found.")

        fields = [field.name() for field in layer.fields()]
        attribute_index = self.parameterAsInt(parameters, self.ATTRIBUTE_FIELD, context)
        attribute_field = fields[attribute_index]

        block_type_index = self.parameterAsInt(parameters, self.BLOCK_TYPE, context)
        block_type = self.BLOCK_TYPES[block_type_index]

        username = self.parameterAsString(parameters, self.FTP_USERNAME, context)
        password = self.parameterAsString(parameters, self.FTP_PASSWORD, context)
        if not username or not password:
            raise QgsProcessingException("FTP username and password are required.")

        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if not os.path.isdir(output_folder):
            raise QgsProcessingException("Output folder does not exist or is not valid.")

        unpack_zip = self.parameterAsBool(parameters, self.UNPACK_ZIP, context)

        selected_features = layer.selectedFeatures()
        if not selected_features:
            raise QgsProcessingException("No features are selected in the active layer.")

        feedback.pushInfo(f"Processing {len(selected_features)} selected features...")

        # Set FTP path and filename format based on block type
        if block_type == 'DTM':
            ftp_path = "/dhm_danmarks_hoejdemodel/DTM/"
            filename_template = "DTM_{grid_id}_TIF_UTM32-ETRS89.zip"
        elif block_type == 'DSM':
            ftp_path = "/dhm_danmarks_hoejdemodel/DSM/"
            filename_template = "DSM_{grid_id}_TIF_UTM32-ETRS89.zip"
        elif block_type == 'Pointclouds':
            ftp_path = "/dhm_danmarks_hoejdemodel/PUNKTSKY/"
            filename_template = "PUNKTSKY_{grid_id}_TIF_UTM32-ETRS89.zip"  # Future change to LAZ

        ftp_server = "ftp.dataforsyningen.dk"
        ftp_port = 990

        ftps = ImplicitFTP_TLS()
        try:
            ftps.connect(ftp_server, ftp_port)
            ftps.login(user=username, passwd=password)
            ftps.prot_p()
            feedback.pushInfo("Connected to FTPS server.")
        except Exception as e:
            raise QgsProcessingException(f"Failed to connect to FTPS server: {str(e)}")

        downloaded_files = 0
        for feature in selected_features:
            grid_id = feature[attribute_field]
            if not grid_id:
                feedback.pushInfo(f"Skipping feature ID {feature.id()} with no grid ID.")
                continue

            # Construct filename based on the selected block type
            filename = filename_template.format(grid_id=grid_id)

            local_filepath = os.path.join(output_folder, filename)
            ftp_filepath = ftp_path + filename

            feedback.pushInfo(f"Downloading {filename} to {local_filepath}...")

            try:
                with open(local_filepath, "wb") as f:
                    ftps.retrbinary(f"RETR {ftp_filepath}", f.write)
                downloaded_files += 1
                feedback.pushInfo(f"Downloaded: {filename}")

                if unpack_zip and filename.lower().endswith('.zip'):
                    feedback.pushInfo(f"Unpacking {filename}...")
                    with zipfile.ZipFile(local_filepath, 'r') as zip_ref:
                        zip_ref.extractall(output_folder)
                        feedback.pushInfo(f"Unpacked: {filename}")
            except Exception as e:
                feedback.reportError(f"Failed to download {filename}: {str(e)}")

        ftps.quit()
        feedback.pushInfo(f"Download complete. {downloaded_files} files downloaded.")

        return {'DOWNLOADED_FILES': downloaded_files}

    def name(self):
        return 'download_Block_files_from_Dataforsyning'

    def displayName(self):
        return self.tr('Download Block Files from Dataforsyning')
    
    def group(self):
        return self.tr('Dataforsyning Preprocessing')

    def groupId(self):
        return 'Dataforsyning_processing'


    def shortHelpString(self):
        return self.tr(
            'Downloads selected Block files (DTM, DSM, or Pointclouds) from Dataforsyningens FTPS server based on the attribute value. '
            'Password is entered in clear text and visible in logs.'
        )

    def createInstance(self):
        return DownloadBlockFilesFromFTPS()
