"""Unit test for preprocessing.nuclei_extraction"""
import unittest
import numpy as np
import cv2 
import os 
import shutil
from PIL import Image
import matplotlib
import yaml

from histocartography import PipelineRunner
from histocartography.preprocessing import NucleiExtractor


class NucleiExtractionTestCase(unittest.TestCase):
    """NucleiExtractionTestCase class."""

    @classmethod
    def setUpClass(self):
        self.data_path = os.path.join('..', 'data')
        self.image_path = os.path.join(self.data_path, 'images')
        self.image_name = '283_dcis_4.png'
        self.out_path = os.path.join(self.data_path, 'nuclei_extraction_test')
        if os.path.exists(self.out_path) and os.path.isdir(self.out_path):
            shutil.rmtree(self.out_path) 
        os.makedirs(self.out_path)

    def test_nuclei_extractor_with_pipeline_runner(self):
        """Test nuclei extraction with local model."""

        with open('config/nuclei_extractor.yml', 'r') as file:
            config = yaml.load(file)

        pipeline = PipelineRunner(output_path=self.out_path, save=True, **config)
        pipeline.precompute()
        output = pipeline.run(
            name=self.image_name.replace('.png', ''),
            image_path=os.path.join(self.image_path, self.image_name)
        )
        instance_map = output['instance_map']
        instance_centroids = output['instance_centroids']

        # 3. run tests 
        self.assertTrue(isinstance(instance_map, np.ndarray))
        self.assertTrue(isinstance(instance_centroids, np.ndarray))
        self.assertEqual(len(instance_centroids), 134)

    def test_nuclei_extractor_with_local_model(self):
        """Test nuclei extraction with local model."""

        # 1. load an image
        image = np.array(Image.open(os.path.join(self.image_path, self.image_name)))

        # 2. extract nuclei
        extractor = NucleiExtractor(
            model_path='../checkpoints/hovernet_monusac.pt'
        )
        instance_map, instance_centroids = extractor.process(image)

        # 3. run tests 
        self.assertEqual(instance_map.shape[0], image.shape[0])
        self.assertEqual(instance_map.shape[1], image.shape[1])
        self.assertEqual(len(instance_centroids), 134)

    def test_nuclei_extractor_with_mlflow_model(self):
        """Test nuclei extraction with local model."""

        # 1. load an image
        image = np.array(Image.open(os.path.join(self.image_path, self.image_name)))

        # 2. extract nuclei
        extractor = NucleiExtractor(
            model_path='s3://mlflow/7cca220ddbff4fef85c600c3606c2cf9/artifacts/hovernet_monusac'
        )
        instance_map, instance_centroids = extractor.process(image)

        # 3. run tests 
        self.assertEqual(instance_map.shape[0], image.shape[0])
        self.assertEqual(instance_map.shape[1], image.shape[1])
        self.assertEqual(len(instance_centroids), 134)

    def tearDown(self):
        """Tear down the tests."""


if __name__ == "__main__":
    unittest.main()