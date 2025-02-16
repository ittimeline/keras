import itertools

import numpy as np
import tree

from keras import backend
from keras.trainers.data_adapters import data_adapter_utils
from keras.trainers.data_adapters.data_adapter import DataAdapter


class GeneratorDataAdapter(DataAdapter):
    """Adapter for Python generators."""

    def __init__(self, generator):
        first_batch, generator = peek_and_restore(generator)
        self.generator = generator
        self._first_batch = first_batch
        self._output_signature = None
        if not isinstance(first_batch, tuple):
            raise ValueError(
                "When passing a Python generator to a Keras model, "
                "the generator must return a tuple, either "
                "(input,) or (inputs, targets) or "
                "(inputs, targets, sample_weights). "
                f"Received: {first_batch}"
            )

    def _set_tf_output_signature(self):
        from keras.utils.module_utils import tensorflow as tf

        def get_tensor_spec(x):
            shape = x.shape
            if len(shape) < 1:
                raise ValueError(
                    "When passing a Python generator to a Keras model, "
                    "the arrays returned by the generator "
                    "must be at least rank 1. Received: "
                    f"{x} of rank {len(x.shape)}"
                )
            shape = list(shape)
            shape[0] = None  # The batch size is not guaranteed to be static.
            dtype = backend.standardize_dtype(x.dtype)
            if isinstance(x, tf.RaggedTensor):
                return tf.RaggedTensorSpec(shape=shape, dtype=dtype)
            if isinstance(x, tf.SparseTensor) or is_scipy_sparse(x):
                return tf.SparseTensorSpec(shape=shape, dtype=dtype)
            else:
                return tf.TensorSpec(shape=shape, dtype=dtype)

        self._output_signature = tree.map_structure(
            get_tensor_spec, self._first_batch
        )

    def get_numpy_iterator(self):
        return data_adapter_utils.get_numpy_iterator(self.generator)

    def get_jax_iterator(self):
        return data_adapter_utils.get_jax_iterator(self.generator)

    def get_tf_dataset(self):
        from keras.utils.module_utils import tensorflow as tf

        def convert_to_tf(batch):
            if is_scipy_sparse(batch):
                batch = scipy_sparse_to_tf_sparse(batch)
            return batch

        def get_tf_iterator():
            for batch in self.generator:
                batch = tree.map_structure(convert_to_tf, batch)
                yield batch

        if self._output_signature is None:
            self._set_tf_output_signature()
        ds = tf.data.Dataset.from_generator(
            get_tf_iterator,
            output_signature=self._output_signature,
        )
        ds = ds.prefetch(tf.data.AUTOTUNE)
        return ds

    def get_torch_dataloader(self):
        return data_adapter_utils.get_torch_dataloader(self.generator)

    @property
    def num_batches(self):
        return None

    @property
    def batch_size(self):
        return None


def peek_and_restore(generator):
    element = next(generator)
    return element, itertools.chain([element], generator)


def is_scipy_sparse(x):
    return x.__class__.__module__.startswith("scipy.sparse") and hasattr(
        x, "tocoo"
    )


def scipy_sparse_to_tf_sparse(x):
    from keras.utils.module_utils import tensorflow as tf

    sparse_coo = x.tocoo()
    row, col = sparse_coo.row, sparse_coo.col
    data, shape = sparse_coo.data, sparse_coo.shape
    indices = np.concatenate(
        (np.expand_dims(row, axis=1), np.expand_dims(col, axis=1)), axis=1
    )
    return tf.SparseTensor(indices, data, shape)
