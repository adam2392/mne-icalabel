from typing import Union

import numpy as np
from mne import BaseEpochs
from mne.io import BaseRaw
from mne.preprocessing import ICA
from mne.utils import _validate_type
from mne.utils.check import _check_option

from .config import ICALABEL_METHODS
from .iclabel.config import ICLABEL_NUMERICAL_TO_STRING
from .utils import _validate_inst_and_ica


def label_components(inst: Union[BaseRaw, BaseEpochs], ica: ICA, method: str):
    """Automatically label the ICA components with the selected method.

    Parameters
    ----------
    inst : Raw | Epochs
        The data instance used to fit the ICA instance.
    ica : ICA
        The fitted ICA instance.
    method : str
        The proposed method for labeling components. Must be one of:
        ``'iclabel'``.

    Returns
    -------
    component_dict : dict
        A dictionary with the following output:
        - 'y_pred_proba' : np.ndarray of shape (n_components,)
        Estimated corresponding predicted probability of the output class
        for each independent component.
        - 'labels': list of shape (n_components,)
        The corresponding string label of each class in 'y_pred'.

    Notes
    -----
    For ICLabel model, the output classes are ordered:
    - 'brain'
    - 'muscle artifact'
    - 'eye blink'
    - 'heart beat'
    - 'line noise'
    - 'channel noise'
    - 'other'
    """
    _validate_type(method, str, "method")
    _check_option("method", method, ICALABEL_METHODS)
    if ICALABEL_METHODS[method] is None:
        raise RuntimeError('Cannot pass in "manual" as a method.')

    _validate_inst_and_ica(inst, ica)
    labels_pred_proba = ICALABEL_METHODS[method](inst, ica)  # type: ignore
    labels_pred = np.argmax(labels_pred_proba, axis=1)
    labels = [ICLABEL_NUMERICAL_TO_STRING[label] for label in labels_pred]
    assert ica.n_components_ == labels_pred.size  # sanity-check
    assert ica.n_components_ == labels_pred_proba.shape[0]  # sanity-check
    y_pred_proba = labels_pred_proba[np.arange(ica.n_components_), labels_pred]

    component_dict = {
        "y_pred_proba": y_pred_proba,
        "labels": labels,
    }
    return component_dict
