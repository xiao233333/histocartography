import numpy as np
from sklearn.metrics import precision_score
import math
import itertools
from scipy import stats
import matplotlib.pyplot as plt 
from typing import Any, Dict, List
from sklearn.preprocessing import minmax_scale
from scipy.stats import wasserstein_distance
from sklearn.metrics import auc

from ..preprocessing.pipeline import PipelineStep


class ExplainerMetric(PipelineStep):
    def __init__(
        self,
        keep_numbers: str = '5,10,15,20,25,30,35,40,45,50',
        tumor_classes: str = '0,1,2',
        **kwargs
    ) -> None:
        """
        ExplainerMetric constructor. 

        Args:
            keep_numbers (str): Number of nuclei to retain each time. Default to '5,10,15,20,25,30,35,40,45,50'. 
            tumor_classes (str): Default to '0,1,2'.
        """
        super().__init__(**kwargs)
        self.keep_numbers = [int(x) for x in keep_numbers.split(',')]
        self.n_keep_numbers = len(self.keep_numbers)
        self.tumor_classes = [int(x) for x in tumor_classes.split(',')]
        self.n_tumors = len(self.tumor_classes)
        self.class_pairs = list(itertools.combinations(self.tumor_classes, 2))
        self.n_class_pairs = len(self.class_pairs)

    def process(
        self,
        nuclei_importance_list: List[np.ndarray], 
        nuclei_concept_list: List[np.ndarray],
        tumor_label_list: List[int]
        ) -> Any:
        """
        Derive metrics based on the explainer importance
        scores and nuclei-level concepts. 

        Args:
            nuclei_importance_list (List[np.ndarray]): List of nuclei importance scores output by explainers. 
            nuclei_concept_list (List[np.ndarray]): List of nuclei-level concepts. 
            tumor_label_list (List[int]): List of tumor-level labels.
        """

        # 1. extract number of concepts
        n_concepts = nuclei_concept_list[0].shape[1]

        # 2. normalize the nuclei concepts & importance scores
        nuclei_importance_list = self.normalize_node_importance(nuclei_importance_list)
        nuclei_concept_list = self.normalize_node_concept(nuclei_concept_list)

        # 3. extract all the histograms å
        all_histograms = self._compute_concept_histograms(nuclei_importance_list, nuclei_concept_list, tumor_label_list)

        # 4. compute the Wasserstein distance for all the class pairs
        all_distances = self._compute_hist_distances(all_histograms, n_concepts)

        # 5. compute the AUC over the #k: output will be Omega x #c
        all_aucs = {}
        for class_pair_id in range(self.n_class_pairs):
            all_aucs[class_pair_id] = {}
            for concept_id in range(n_concepts):
                all_aucs[class_pair_id][concept_id] = auc(self.keep_numbers, all_distances[:, class_pair_id, concept_id])

        return all_aucs

    def _compute_hist_distances(self, all_histograms: Dict, n_concepts: int):
        """
        Compute all the pair-wise histogram distances. 

        Args:
             all_histograms (Dict): all the histograms. 
             n_concepts (int): number of concepts. 
        """
        all_distances = np.empty((self.n_keep_numbers, self.n_class_pairs, n_concepts))
        for k_id , k in enumerate(self.keep_numbers):
            omega = 0
            for tx in range(self.n_tumors):
                for ty in range(self.n_tumors):
                    if tx < ty:
                        for concept_id in range(n_concepts):
                            all_distances[k_id, omega, concept_id] = wasserstein_distance(
                                all_histograms[k][tx][concept_id],
                                all_histograms[k][ty][concept_id]
                            )
                        omega += 1
        return all_distances

    def _compute_concept_histograms(
        self, 
        importance_list: List[np.ndarray], 
        concept_list: List[np.ndarray],
        label_list: List[int]
        ) -> Dict:
        """
        Compute histograms for all the concepts. 

        Args:
            importance_list (List[np.ndarray]): List of nuclei importance scores output by explainers. 
            concept_list (List[np.ndarray]): List of nuclei-level concepts. 
            label_list (List[int]): List of tumor-level labels.
        Returns:
            all_histograms (Dict): Dict with all the histograms for each concept, tumor type, thresh k.
        """
        all_histograms = {}
        for k in self.keep_numbers:
            all_histograms[k] = {}
            for t in range(self.n_tumors):

                # i. extract the importance and concept of type t
                scores = [s for l, s in zip(label_list, importance_list) if l==t]
                concepts = [s for l, s in zip(label_list, concept_list) if l==t]

                # ii. extract the k largest scores & merge 
                concepts = [c[np.argsort(s)[:k]] for c, s in zip(concepts, scores)]
                concepts = np.concatenate(concepts, axis=0)

                # iii. build the histogram for all the concepts (dim = #nuclei x concept_types)
                all_histograms[k][t] = np.array(
                    [self.build_hist(concepts[:, concept_id]) for concept_id in range(concepts.shape[1])]
                )
        return all_histograms

    @staticmethod
    def normalize_node_importance(node_importance: List[np.ndarray]):
        """
        Normalize node importance. Min-max normalization on each sample. 

        Args:
            node_importance (List[np.ndarray]): node importance output by an explainer. 
        Returns:
            node_importance (List[np.ndarray]): Normalized node importance. 
        """
        node_importance = [minmax_scale(x) for x in node_importance] 
        return node_importance

    @staticmethod
    def normalize_node_concept(node_concepts: List[np.ndarray]):
        """
        Normalize node concepts. Min-max normalization on each concept over
        all the samples. 

        Args:
            node_concepts: List[np.ndarray]: Each element in the list are nuclei concept 
                                             for a sample stored as np.ndarray with dim
                                             #nuclei x #concepts.
        Returns:
            node_concepts: List[np.ndarray]: Normalized node concepts.  
        """

        stacked = np.concatenate(node_concepts, axis=0)  
        stacked = minmax_scale(stacked) 

        def extract_and_drop(s, stacked):
            out = stacked[:s.shape[0], :]
            stacked = np.delete(stacked, list(range(s.shape[0])), axis=0)
            return out, stacked

        out = []
        for s in node_concepts:
            x, stacked = extract_and_drop(s, stacked)
            out.append(x)

        return out

    @staticmethod
    def build_hist(concept_values: np.ndarray, num_bins: int = 100):
        """
        Build a 1D histogram using the concept_values. 

        Args:
            concept_values (np.ndarray): All the nuclei-level values for a concept. 
            num_bins (int): Number of bins in the histogram. Default to 100. 
        Returns:
            hist (np.ndarray): Histogram
        """
        bins = np.linspace(np.min(concept_values), np.max(concept_values), num=num_bins)
        hist, _ = np.histogram(concept_values, bins=bins, density=True)
        return hist
