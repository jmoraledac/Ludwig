import logging

from ludwig.constants import MODEL_ECD, MODEL_GBM, MODEL_LLM
from ludwig.models.ecd import ECD
from ludwig.models.llm import LLM

logger = logging.getLogger(__name__)


def gbm(*args, **kwargs):
    try:
        from ludwig.models.gbm import GBM
    except ImportError:
        logger.warning(
            "Importing GBM requirements failed. Not loading GBM model type. "
            "If you want to use GBM, install Ludwig's 'tree' extra."
        )
        raise

    return GBM(*args, **kwargs)


model_type_registry = {
    MODEL_ECD: ECD,
    MODEL_GBM: gbm,
    MODEL_LLM: LLM,
}
