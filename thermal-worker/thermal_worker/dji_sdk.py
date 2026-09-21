from __future__ import annotations

import ctypes
import logging
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np


logger = logging.getLogger(__name__)


DIRP_SUCCESS = 0
DIRP_ERROR_UNSUPPORTED_FUNC = -12
DIRP_ERROR_NOT_READY = -13

_ERROR_NAMES = {
    0: "SUCCESS",
    -1: "MALLOC",
    -2: "POINTER_NULL",
    -3: "INVALID_PARAMS",
    -4: "INVALID_RAW",
    -5: "INVALID_HEADER",
    -6: "INVALID_CURVE",
    -7: "RJPEG_PARSE",
    -8: "SIZE",
    -9: "INVALID_HANDLE",
    -10: "FORMAT_INPUT",
    -11: "FORMAT_OUTPUT",
    -12: "UNSUPPORTED_FUNC",
    -13: "NOT_READY",
    -14: "ACTIVATION",
    -32: "ADVANCED",
}


class ThermalSdkError(RuntimeError):
    def __init__(self, operation: str, code: int, detail: str | None = None):
        name = _ERROR_NAMES.get(code, "UNKNOWN")
        suffix = f": {detail}" if detail else ""
        super().__init__(f"{operation} failed with DJI DIRP {code} ({name}){suffix}")
        self.operation = operation
        self.code = code


@dataclass(frozen=True)
class MeasurementParams:
    distance_m: float
    humidity_pct: float
    emissivity: float
    reflection_c: float
    ambient_temp_c: float

    def as_dict(self) -> dict[str, float]:
        return {
            "distance_m": self.distance_m,
            "humidity_pct": self.humidity_pct,
            "emissivity": self.emissivity,
            "reflection_c": self.reflection_c,
            "ambient_temp_c": self.ambient_temp_c,
        }


@dataclass(frozen=True)
class DecodeResult:
    temperature_c: np.ndarray
    width: int
    height: int
    rjpeg_version: dict[str, int]
    measurement_params: MeasurementParams | None
    measurement_mode: str
    measurement_error_code: int | None
    sdk_label: str


class _DirpRjpegVersion(ctypes.Structure):
    _fields_ = [
        ("rjpeg", ctypes.c_uint32),
        ("header", ctypes.c_uint32),
        ("curve", ctypes.c_uint32),
    ]


class _DirpResolution(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
    ]


class _DirpMeasurementParams(ctypes.Structure):
    # Modern DJI TSDK ABI (including 1.8) adds ambient_temp after reflection.
    # Keeping the exact field order is required for ctypes/C ABI compatibility.
    _fields_ = [
        ("distance", ctypes.c_float),
        ("humidity", ctypes.c_float),
        ("emissivity", ctypes.c_float),
        ("reflection", ctypes.c_float),
        ("ambient_temp", ctypes.c_float),
    ]


class DjiThermalSdk:
    """Thin, fail-closed ctypes wrapper around DJI's DIRP R-JPEG API.

    DJI Thermal SDK binaries are intentionally not distributed with M3-Cloud.
    The worker loads them from a user-provided TSDK release directory.
    """

    def __init__(self, sdk_dir: str | os.PathLike[str], *, sdk_label: str | None = None):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("M3 thermal worker currently requires a 64-bit Python runtime")

        self.sdk_dir = Path(sdk_dir).expanduser().resolve()
        self.release_dir = self._resolve_release_dir(self.sdk_dir)
        self.sdk_label = sdk_label or os.environ.get("DJI_TSDK_VERSION") or self.sdk_dir.name
        self._dll_directory_handle = None
        self._library = self._load_library()
        self._bind()

    @staticmethod
    def _resolve_release_dir(root: Path) -> Path:
        if not root.exists():
            raise FileNotFoundError(f"DJI Thermal SDK directory not found: {root}")

        system = platform.system()
        library_name = "libdirp.dll" if system == "Windows" else "libdirp.so"
        direct = root / library_name
        if direct.is_file():
            return root

        candidates = [
            path.parent
            for path in root.rglob(library_name)
            if "x64" in path.parent.name.lower() or "x86_64" in path.parent.name.lower()
        ]
        if not candidates:
            raise FileNotFoundError(
                f"{library_name} x64 release not found below DJI Thermal SDK directory: {root}"
            )
        candidates.sort(key=lambda item: (len(item.parts), str(item)))
        return candidates[0]

    def _load_library(self) -> ctypes.CDLL:
        system = platform.system()
        if system not in {"Linux", "Windows"}:
            raise NotImplementedError(f"DJI Thermal SDK worker does not support {system}")

        if system == "Windows":
            if hasattr(os, "add_dll_directory"):
                self._dll_directory_handle = os.add_dll_directory(str(self.release_dir))
            library_path = self.release_dir / "libdirp.dll"
            try:
                return ctypes.CDLL(str(library_path))
            except OSError as exc:
                raise OSError(
                    f"Unable to load DJI Thermal SDK from {library_path}: {exc}"
                ) from exc

        library_path = self.release_dir / "libdirp.so"
        # DJI packages helper libraries beside libdirp. Preload what can be loaded
        # globally so libdirp can resolve optional codec/IR processing symbols.
        mode = getattr(ctypes, "RTLD_GLOBAL", 0)
        deferred: list[tuple[Path, OSError]] = []
        for helper in sorted(self.release_dir.glob("*.so*")):
            if helper.name == "libdirp.so":
                continue
            try:
                ctypes.CDLL(str(helper), mode=mode)
            except OSError as exc:
                deferred.append((helper, exc))
        try:
            return ctypes.CDLL(str(library_path), mode=mode)
        except OSError as exc:
            helper_errors = "; ".join(
                f"{path.name}: {error}" for path, error in deferred[:4]
            )
            detail = f"; helper preload errors: {helper_errors}" if helper_errors else ""
            raise OSError(
                f"Unable to load DJI Thermal SDK from {library_path}: {exc}{detail}"
            ) from exc

    def _bind(self) -> None:
        handle_p = ctypes.POINTER(ctypes.c_void_p)
        uint8_p = ctypes.POINTER(ctypes.c_uint8)

        self._create = self._library.dirp_create_from_rjpeg
        self._create.argtypes = [uint8_p, ctypes.c_int32, handle_p]
        self._create.restype = ctypes.c_int32

        self._destroy = self._library.dirp_destroy
        self._destroy.argtypes = [ctypes.c_void_p]
        self._destroy.restype = ctypes.c_int32

        self._get_version = self._library.dirp_get_rjpeg_version
        self._get_version.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DirpRjpegVersion),
        ]
        self._get_version.restype = ctypes.c_int32

        self._get_resolution = self._library.dirp_get_rjpeg_resolution
        self._get_resolution.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DirpResolution),
        ]
        self._get_resolution.restype = ctypes.c_int32

        self._get_measurement = self._library.dirp_get_measurement_params
        self._get_measurement.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DirpMeasurementParams),
        ]
        self._get_measurement.restype = ctypes.c_int32

        self._set_measurement = self._library.dirp_set_measurement_params
        self._set_measurement.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DirpMeasurementParams),
        ]
        self._set_measurement.restype = ctypes.c_int32

        self._measure_ex = self._library.dirp_measure_ex
        self._measure_ex.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int32,
        ]
        self._measure_ex.restype = ctypes.c_int32

        verbose = getattr(self._library, "dirp_set_verbose_level", None)
        if verbose is not None:
            verbose.argtypes = [ctypes.c_int]
            verbose.restype = ctypes.c_int32
            verbose(0)

    @staticmethod
    def _check(operation: str, code: int) -> None:
        if code != DIRP_SUCCESS:
            raise ThermalSdkError(operation, int(code))

    @staticmethod
    def _validate_overrides(overrides: Mapping[str, float] | None) -> dict[str, float]:
        if not overrides:
            return {}
        result = {str(key): float(value) for key, value in overrides.items()}
        ranges = {
            "distance_m": (1.0, 25.0),
            "humidity_pct": (20.0, 100.0),
            "emissivity": (0.10, 1.00),
            "reflection_c": (-40.0, 500.0),
            "ambient_temp_c": (-50.0, 80.0),
        }
        unknown = set(result) - set(ranges)
        if unknown:
            raise ValueError(f"Unsupported measurement overrides: {sorted(unknown)}")
        for key, value in result.items():
            minimum, maximum = ranges[key]
            if not np.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(
                    f"{key} must be finite and in [{minimum}, {maximum}], got {value}"
                )
        return result

    def decode_file(
        self,
        path: str | os.PathLike[str],
        *,
        overrides: Mapping[str, float] | None = None,
    ) -> DecodeResult:
        source = Path(path)
        raw = source.read_bytes()
        if not raw:
            raise ValueError(f"Empty R-JPEG input: {source}")
        return self.decode_bytes(raw, overrides=overrides)

    def decode_bytes(
        self,
        raw: bytes,
        *,
        overrides: Mapping[str, float] | None = None,
    ) -> DecodeResult:
        if len(raw) > 2_147_483_647:
            raise ValueError("R-JPEG exceeds DJI DIRP int32 input-size limit")

        requested = self._validate_overrides(overrides)
        raw_buffer = (ctypes.c_uint8 * len(raw)).from_buffer_copy(raw)
        handle = ctypes.c_void_p()
        created = False

        try:
            code = self._create(
                ctypes.cast(raw_buffer, ctypes.POINTER(ctypes.c_uint8)),
                ctypes.c_int32(len(raw)),
                ctypes.byref(handle),
            )
            self._check("dirp_create_from_rjpeg", int(code))
            created = True

            version = _DirpRjpegVersion()
            self._check(
                "dirp_get_rjpeg_version",
                int(self._get_version(handle, ctypes.byref(version))),
            )

            resolution = _DirpResolution()
            self._check(
                "dirp_get_rjpeg_resolution",
                int(self._get_resolution(handle, ctypes.byref(resolution))),
            )
            width = int(resolution.width)
            height = int(resolution.height)
            if width <= 0 or height <= 0 or width * height > 100_000_000:
                raise ThermalSdkError(
                    "dirp_get_rjpeg_resolution",
                    -8,
                    f"invalid resolution {width}x{height}",
                )

            params = _DirpMeasurementParams()
            measurement_code = int(
                self._get_measurement(handle, ctypes.byref(params))
            )
            measurement: MeasurementParams | None = None
            measurement_mode = "sdk_native"
            measurement_error_code: int | None = None

            if measurement_code == DIRP_SUCCESS:
                measurement = MeasurementParams(
                    distance_m=float(params.distance),
                    humidity_pct=float(params.humidity),
                    emissivity=float(params.emissivity),
                    reflection_c=float(params.reflection),
                    ambient_temp_c=float(params.ambient_temp),
                )
                if requested:
                    params.distance = requested.get("distance_m", measurement.distance_m)
                    params.humidity = requested.get("humidity_pct", measurement.humidity_pct)
                    params.emissivity = requested.get("emissivity", measurement.emissivity)
                    params.reflection = requested.get("reflection_c", measurement.reflection_c)
                    params.ambient_temp = requested.get(
                        "ambient_temp_c",
                        measurement.ambient_temp_c,
                    )
                    set_code = int(
                        self._set_measurement(handle, ctypes.byref(params))
                    )
                    if set_code == DIRP_SUCCESS:
                        measurement = MeasurementParams(
                            distance_m=float(params.distance),
                            humidity_pct=float(params.humidity),
                            emissivity=float(params.emissivity),
                            reflection_c=float(params.reflection),
                            ambient_temp_c=float(params.ambient_temp),
                        )
                        measurement_mode = "overridden"
                    elif set_code in {DIRP_ERROR_UNSUPPORTED_FUNC, DIRP_ERROR_NOT_READY}:
                        raise ThermalSdkError(
                            "dirp_set_measurement_params",
                            set_code,
                            "measurement overrides were requested but this R-JPEG does not allow them",
                        )
                    else:
                        raise ThermalSdkError("dirp_set_measurement_params", set_code)
            elif measurement_code in {DIRP_ERROR_UNSUPPORTED_FUNC, DIRP_ERROR_NOT_READY}:
                if requested:
                    raise ThermalSdkError(
                        "dirp_get_measurement_params",
                        measurement_code,
                        "measurement overrides were requested but this R-JPEG exposes no editable parameters",
                    )
                measurement_mode = "sdk_native_locked"
                measurement_error_code = measurement_code
            else:
                # Decoding can still be valid when a product does not expose editable
                # measurement parameters. Preserve the failure as provenance rather than
                # silently fabricating settings.
                if requested:
                    raise ThermalSdkError(
                        "dirp_get_measurement_params",
                        measurement_code,
                        "measurement overrides were requested but current parameters could not be read",
                    )
                measurement_mode = "sdk_native_unreadable"
                measurement_error_code = measurement_code

            data = np.empty(width * height, dtype=np.float32)
            size_bytes = data.nbytes
            if size_bytes > 2_147_483_647:
                raise ValueError("Decoded temperature plane exceeds DJI DIRP int32 output limit")
            code = int(
                self._measure_ex(
                    handle,
                    data.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                    ctypes.c_int32(size_bytes),
                )
            )
            self._check("dirp_measure_ex", code)
            temperature = data.reshape((height, width))
            if not np.isfinite(temperature).any():
                raise ThermalSdkError(
                    "dirp_measure_ex",
                    -32,
                    "temperature plane contains no finite samples",
                )

            return DecodeResult(
                temperature_c=temperature,
                width=width,
                height=height,
                rjpeg_version={
                    "rjpeg": int(version.rjpeg),
                    "header": int(version.header),
                    "curve": int(version.curve),
                },
                measurement_params=measurement,
                measurement_mode=measurement_mode,
                measurement_error_code=measurement_error_code,
                sdk_label=self.sdk_label,
            )
        finally:
            if created and handle.value:
                try:
                    self._destroy(handle)
                except (OSError, ctypes.ArgumentError) as exc:
                    # Never mask the primary decode exception with cleanup failure.
                    logger.warning("DJI DIRP handle cleanup failed: %s", exc)
