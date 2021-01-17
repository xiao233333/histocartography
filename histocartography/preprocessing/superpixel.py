"""This module handles everything related to superpixels"""

import logging
import math
from abc import abstractmethod

import cv2
import numpy as np
from skimage import color, filters
from skimage.color.colorconv import rgb2hed
from skimage.future import graph
from skimage.segmentation import slic

from .pipeline import PipelineStep


class SuperpixelExtractor(PipelineStep):
    """Helper class to extract superpixels from images"""

    def __init__(self, downsampling_factor: int = 1, **kwargs) -> None:
        """Abstract class that extracts superpixels from RGB Images

        Args:
            nr_superpixels (int): Upper bound of super pixels
            downsampling_factor (int, optional): Downsampling factor from the input image
                                                 resolution. Defaults to 1.
        """
        self.downsampling_factor = downsampling_factor
        super().__init__(**kwargs)

    def process(self, input_image: np.ndarray) -> np.ndarray:
        """Return the superpixels of a given input image

        Args:
            input_image (np.array): Input image

        Returns:
            np.array: Extracted superpixels
        """
        logging.debug("Input size: %s", input_image.shape)
        original_height, original_width, _ = input_image.shape
        if self.downsampling_factor != 1:
            input_image = self._downsample(input_image, self.downsampling_factor)
            logging.debug("Downsampled to %s", input_image.shape)
        superpixels = self._extract_superpixels(input_image)
        if self.downsampling_factor != 1:
            superpixels = self._upsample(superpixels, original_height, original_width)
            logging.debug("Upsampled to %s", superpixels.shape)
        return superpixels

    @abstractmethod
    def _extract_superpixels(self, image: np.ndarray) -> np.ndarray:
        """Perform the superpixel extraction

        Args:
            image (np.array): Input tensor

        Returns:
            np.array: Output tensor
        """

    @staticmethod
    def _downsample(image: np.ndarray, downsampling_factor: int) -> np.ndarray:
        """Downsample an input image with a given downsampling factor

        Args:
            image (np.array): Input tensor
            downsampling_factor (int): Factor to downsample

        Returns:
            np.array: Output tensor
        """
        height, width = image.shape[0], image.shape[1]
        new_height = math.floor(height / downsampling_factor)
        new_width = math.floor(width / downsampling_factor)
        downsampled_image = cv2.resize(
            image, (new_height, new_width), interpolation=cv2.INTER_NEAREST
        )
        return downsampled_image

    @staticmethod
    def _upsample(image: np.ndarray, new_height: int, new_width: int) -> np.ndarray:
        """Upsample an input image to a speficied new height and width

        Args:
            image (np.array): Input tensor
            new_height (int): Target height
            new_width (int): Target width

        Returns:
            np.array: Output tensor
        """
        upsampled_image = cv2.resize(
            image, (new_height, new_width), interpolation=cv2.INTER_NEAREST
        )
        return upsampled_image


class SLICSuperpixelExtractor(SuperpixelExtractor):
    """Use the SLIC algorithm to extract superpixels"""

    def __init__(
        self,
        nr_superpixels: int,
        blur_kernel_size: float = 0,
        max_iter: int = 10,
        compactness: int = 30,
        color_space: str = "rgb",
        **kwargs,
    ) -> None:
        """Extract superpixels with the SLIC algorithm

        Args:
            blur_kernel_size (float, optional): Size of the blur kernel. Defaults to 0.
            max_iter (int, optional): Number of iterations of the slic algorithm. Defaults to 10.
            compactness (int, optional): Compactness of the superpixels. Defaults to 30.
        """
        self.nr_superpixels = nr_superpixels
        self.blur_kernel_size = blur_kernel_size
        self.max_iter = max_iter
        self.compactness = compactness
        self.color_space = color_space
        super().__init__(**kwargs)

    def _extract_superpixels(self, image: np.ndarray) -> np.ndarray:
        """Perform the superpixel extraction

        Args:
            image (np.array): Input tensor

        Returns:
            np.array: Output tensor
        """
        if self.color_space == "hed":
            image = rgb2hed(image)
        superpixels = slic(
            image,
            sigma=self.blur_kernel_size,
            n_segments=self.nr_superpixels,
            max_iter=self.max_iter,
            compactness=self.compactness,
        )
        superpixels += 1  # Handle regionprops that ignores all values of 0
        return superpixels


class SuperpixelMerger(SuperpixelExtractor):
    def __init__(
        self,
        downsampling_factor: int,
        threshold: float = 0.06,
        connectivity: int = 2,
        **kwargs,
    ) -> None:
        self.threshold = threshold
        self.connectivity = connectivity
        super().__init__(downsampling_factor=downsampling_factor, **kwargs)

    def process(self, input_image: np.ndarray, superpixels: np.ndarray) -> np.ndarray:
        logging.debug("Input size: %s", input_image.shape)
        original_height, original_width, _ = input_image.shape
        if self.downsampling_factor != 1:
            input_image = self._downsample(input_image, self.downsampling_factor)
            superpixels = self._downsample(superpixels, self.downsampling_factor)
            logging.debug("Downsampled to %s", input_image.shape)
        merged_superpixels = self._extract_superpixels(input_image, superpixels)
        if self.downsampling_factor != 1:
            merged_superpixels = self._upsample(
                merged_superpixels, original_height, original_width
            )
            logging.debug("Upsampled to %s", merged_superpixels.shape)
        return merged_superpixels

    def _generate_graph(self, input_image, superpixels):
        edges = filters.sobel(color.rgb2gray(input_image))
        return graph.rag_boundary(superpixels, edges, connectivity=self.connectivity)

    def _extract_superpixels(self, input_image, superpixels):
        g = self._generate_graph(input_image, superpixels)
        merged_superpixels = graph.merge_hierarchical(
            superpixels,
            g,
            thresh=self.threshold,
            rag_copy=False,
            in_place_merge=True,
            merge_func=self._merge_boundary,
            weight_func=self._weight_boundary,
        )
        merged_superpixels += 1  # Handle regionprops that ignores all values of 0
        return merged_superpixels

    @staticmethod
    def _weight_boundary(graph, src, dst, n):
        """
        Handle merging of nodes of a region boundary region adjacency graph.

        This function computes the `"weight"` and the count `"count"`
        attributes of the edge between `n` and the node formed after
        merging `src` and `dst`.


        Parameters
        ----------
        graph : RAG
            The graph under consideration.
        src, dst : int
            The vertices in `graph` to be merged.
        n : int
            A neighbor of `src` or `dst` or both.

        Returns
        -------
        data : dict
            A dictionary with the "weight" and "count" attributes to be
            assigned for the merged node.

        """
        default = {"weight": 0.0, "count": 0}

        count_src = graph[src].get(n, default)["count"]
        count_dst = graph[dst].get(n, default)["count"]

        weight_src = graph[src].get(n, default)["weight"]
        weight_dst = graph[dst].get(n, default)["weight"]

        count = count_src + count_dst
        return {
            "count": count,
            "weight": (count_src * weight_src + count_dst * weight_dst) / count,
        }

    @staticmethod
    def _merge_boundary(graph, src, dst):
        """Call back called before merging 2 nodes.

        In this case we don't need to do any computation here.
        """
        pass


class SpecialSuperpixelMerger(SuperpixelMerger):
    def __init__(
        self,
        downsampling_factor: int,
        w_hist: float = 0.5,
        w_mean: float = 0.5,
        **kwargs,
    ) -> None:
        self.w_hist = w_hist
        self.w_mean = w_mean
        super().__init__(downsampling_factor, **kwargs)

    def _color_features_per_channel(self, img_ch):
        hist, _ = np.histogram(img_ch, bins=np.arange(0, 257, 64))  # 8 bins
        return hist

    def _generate_graph(self, input_image, superpixels):
        g = graph.RAG(superpixels, connectivity=self.connectivity)

        for n in g:
            g.nodes[n].update(
                {
                    "labels": [n],
                    "N": 0,
                    "x": np.array([0, 0, 0]),
                    "y": np.array([0, 0, 0]),
                    "r": np.array([]),
                    "g": np.array([]),
                    "b": np.array([]),
                }
            )

        for index in np.ndindex(superpixels.shape):
            current = superpixels[index]
            g.nodes[current]["N"] += 1
            g.nodes[current]["x"] += input_image[index]
            g.nodes[current]["y"] = np.vstack(
                (g.nodes[current]["y"], input_image[index])
            )

        for n in g:
            g.nodes[n]["mean"] = g.nodes[n]["x"] / g.nodes[n]["N"]
            g.nodes[n]["mean"] = g.nodes[n]["mean"] / np.linalg.norm(g.nodes[n]["mean"])

            g.nodes[n]["y"] = np.delete(g.nodes[n]["y"], 0, axis=0)
            g.nodes[n]["r"] = self._color_features_per_channel(g.nodes[n]["y"][:, 0])
            g.nodes[n]["g"] = self._color_features_per_channel(g.nodes[n]["y"][:, 1])
            g.nodes[n]["b"] = self._color_features_per_channel(g.nodes[n]["y"][:, 2])

            g.nodes[n]["r"] = g.nodes[n]["r"] / np.linalg.norm(g.nodes[n]["r"])
            g.nodes[n]["g"] = g.nodes[n]["r"] / np.linalg.norm(g.nodes[n]["g"])
            g.nodes[n]["b"] = g.nodes[n]["r"] / np.linalg.norm(g.nodes[n]["b"])

        for x, y, d in g.edges(data=True):
            diff_mean = np.linalg.norm(g.nodes[x]["mean"] - g.nodes[y]["mean"]) / 2

            diff_r = np.linalg.norm(g.nodes[x]["r"] - g.nodes[y]["r"]) / 2
            diff_g = np.linalg.norm(g.nodes[x]["g"] - g.nodes[y]["g"]) / 2
            diff_b = np.linalg.norm(g.nodes[x]["b"] - g.nodes[y]["b"]) / 2
            diff_hist = (diff_r + diff_g + diff_b) / 3

            diff = self.w_hist * diff_hist + self.w_mean * diff_mean

            d["weight"] = diff

        return g

    def _weight_boundary(self, graph, src, dst, n):
        diff_mean = np.linalg.norm(graph.nodes[dst]["mean"] - graph.nodes[n]["mean"])

        diff_r = np.linalg.norm(graph.nodes[dst]["r"] - graph.nodes[n]["r"]) / 2
        diff_g = np.linalg.norm(graph.nodes[dst]["g"] - graph.nodes[n]["g"]) / 2
        diff_b = np.linalg.norm(graph.nodes[dst]["b"] - graph.nodes[n]["b"]) / 2
        diff_hist = (diff_r + diff_g + diff_b) / 3

        diff = self.w_hist * diff_hist + self.w_mean * diff_mean

        return {"weight": diff}

    def _merge_boundary(self, graph, src, dst):
        graph.nodes[dst]["x"] += graph.nodes[src]["x"]
        graph.nodes[dst]["N"] += graph.nodes[src]["N"]
        graph.nodes[dst]["mean"] = graph.nodes[dst]["x"] / graph.nodes[dst]["N"]
        graph.nodes[dst]["mean"] = graph.nodes[dst]["mean"] / np.linalg.norm(
            graph.nodes[dst]["mean"]
        )

        graph.nodes[dst]["y"] = np.vstack(
            (graph.nodes[dst]["y"], graph.nodes[src]["y"])
        )
        graph.nodes[dst]["r"] = self._color_features_per_channel(
            graph.nodes[dst]["y"][:, 0]
        )
        graph.nodes[dst]["g"] = self._color_features_per_channel(
            graph.nodes[dst]["y"][:, 1]
        )
        graph.nodes[dst]["b"] = self._color_features_per_channel(
            graph.nodes[dst]["y"][:, 2]
        )

        graph.nodes[dst]["r"] = graph.nodes[dst]["r"] / np.linalg.norm(
            graph.nodes[dst]["r"]
        )
        graph.nodes[dst]["g"] = graph.nodes[dst]["r"] / np.linalg.norm(
            graph.nodes[dst]["g"]
        )
        graph.nodes[dst]["b"] = graph.nodes[dst]["r"] / np.linalg.norm(
            graph.nodes[dst]["b"]
        )
