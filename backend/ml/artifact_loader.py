"""Load trusted serving artefacts without restoring platform-specific RNG state.

XGBoost's pickle snapshot contains a portable ``Model`` UBJSON object and a
training ``Config`` object. Linux RNG state in Config cannot be restored by
some Windows wheels (upstream issue #12459). For inference we pass the original
Model bytes, unchanged, to XGBoost's supported model loader. Trees, objective,
attributes and feature metadata are retained; training-resumption state is not.

This loader is for this project's trusted, uncompressed joblib files only.
It does not make pickle safe for user uploads. Training still uses joblib's
normal persistence; no serving artefact is rewritten by this module.
"""

from __future__ import annotations

import inspect
import struct
from pathlib import Path
from typing import Any


class SnapshotFormatError(ValueError):
    """The snapshot is not the supported XGBoost UBJSON representation."""


class _Cursor:
    """Locate UBJSON values without decoding or re-encoding numeric contents."""

    _sizes = {b'i': 1, b'U': 1, b'I': 2, b'l': 4, b'L': 8, b'd': 4, b'D': 8, b'C': 1}
    _ints = {b'i': '>b', b'U': '>B', b'I': '>h', b'l': '>i', b'L': '>q'}

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SnapshotFormatError('Truncated UBJSON snapshot.')
        start = self.pos
        self.pos += count
        return bytes(self.data[start:self.pos])

    def peek(self) -> bytes:
        return bytes(self.data[self.pos:self.pos + 1])

    def length(self) -> int:
        marker = self.take(1)
        if marker not in self._ints:
            raise SnapshotFormatError('Unsupported UBJSON length marker.')
        count = struct.unpack(self._ints[marker], self.take(self._sizes[marker]))[0]
        if count < 0 or count > len(self.data):
            raise SnapshotFormatError('Invalid UBJSON length.')
        return count

    def key(self) -> bytes:
        return self.take(self.length())

    def skip(self, depth: int = 0, marker: bytes | None = None) -> None:
        if depth > 64:
            raise SnapshotFormatError('UBJSON nesting is too deep.')
        marker = self.take(1) if marker is None else marker
        if marker in self._sizes:
            self.take(self._sizes[marker])
        elif marker in (b'Z', b'T', b'F', b'N'):
            return
        elif marker in (b'S', b'H'):
            self.take(self.length())
        elif marker in (b'[', b'{'):
            forced = None
            if self.peek() == b'$':
                self.take(1)
                forced = self.take(1)
            count = None
            if self.peek() == b'#':
                self.take(1)
                count = self.length()
            elif forced is not None:
                raise SnapshotFormatError('Typed UBJSON container requires a count.')
            end = b']' if marker == b'[' else b'}'
            if marker == b'[' and forced in self._sizes and count is not None:
                self.take(count * self._sizes[forced])
                return
            if count is not None:
                for _ in range(count):
                    if marker == b'{':
                        self.key()
                    self.skip(depth + 1, forced)
            else:
                while self.peek() != end:
                    if marker == b'{':
                        self.key()
                    self.skip(depth + 1)
                self.take(1)
        else:
            raise SnapshotFormatError('Unsupported UBJSON value marker.')


def snapshot_model_bytes(snapshot: bytes | bytearray) -> bytearray:
    """Extract the exact XGBoost-generated Model object; fail on unknown formats."""
    cursor = _Cursor(snapshot)
    if cursor.take(1) != b'{':
        raise SnapshotFormatError('Expected an XGBoost UBJSON snapshot object.')
    model = None
    while cursor.peek() != b'}':
        key = cursor.key()
        start = cursor.pos
        cursor.skip()
        if key == b'Model':
            if model is not None or snapshot[start:start + 1] != b'{':
                raise SnapshotFormatError('Expected exactly one Model object.')
            model = bytearray(snapshot[start:cursor.pos])
    cursor.take(1)
    if cursor.pos != len(snapshot) or model is None:
        raise SnapshotFormatError('Snapshot has no Model object or contains trailing bytes.')
    return model


def load_inference_artifact(path: str | Path) -> Any:
    """Restore a trusted joblib artefact using portable XGBoost model state."""
    import joblib
    import xgboost

    class InferenceBooster(xgboost.Booster):
        def __setstate__(self, state: dict[str, Any]) -> None:
            # Initialise a fresh handle using supported model IO; never invoke
            # the snapshot deserializer or change process-global pickle hooks.
            model = snapshot_model_bytes(state['handle'])
            super().__init__(model_file=model)
            self.__dict__.update({key: value for key, value in state.items() if key != 'handle'})

    class InferenceUnpickler(joblib.numpy_pickle.NumpyUnpickler):
        def find_class(self, module: str, name: str) -> Any:
            if (module, name) == ('xgboost.core', 'Booster'):
                return InferenceBooster
            return super().find_class(module, name)

    kwargs = {'mmap_mode': None}
    # joblib 1.5 added this argument; support the existing >=1.4 requirement.
    if 'ensure_native_byte_order' in inspect.signature(InferenceUnpickler).parameters:
        kwargs['ensure_native_byte_order'] = True
    path = Path(path)
    with path.open('rb') as stream:
        return InferenceUnpickler(str(path), stream, **kwargs).load()
