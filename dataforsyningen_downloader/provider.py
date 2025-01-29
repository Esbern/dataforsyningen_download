from qgis.core import QgsProcessingProvider
from .processing.load_index_file import Load10KmIndexFile  # Import your scripts
from .processing.download_blocks import DownloadBlockFilesFromFTPS  # Import your scripts


class MyProcessingProvider(QgsProcessingProvider):
    def loadAlgorithms(self):
        """Register algorithms."""
        self.addAlgorithm(Load10KmIndexFile())  # Add each algorithm here
        self.addAlgorithm(DownloadBlockFilesFromFTPS()) 


    def id(self):
        """Unique provider ID."""
        return 'dataforsyning_processingsing'

    def name(self):
        """Provider name shown in QGIS."""
        return 'Dataforsyningen Processing'
    def longName(self):
        """Detailed provider name."""
        return 'Collection os scripts for downloafing and frocessing files from dataforsyningen.dk'
