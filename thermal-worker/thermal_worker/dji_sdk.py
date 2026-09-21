from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import platform
import re
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
    -15: "INVALID_INI",
    -16: "INVALID_SUB_DLL",
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
    ambient_temp_c: float | None

    def as_dict(self) -> dict[str, float | None]:
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
    api_version: dict[str, int | str]
    rjpeg_version: dict[str, int]
    measurement_params: MeasurementParams | None
    measurement_ranges: dict[str, dict[str, float]] | None
    measurement_mode: str
    measurement_error_code: int | None
    sdk_label: str
    measurement_abi: str
    sdk_library_name: str | None = None
    sdk_library_sha256: str | None = None


class _DirpApiVersion(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("api", ctypes.c_uint32),
        ("magic", ctypes.c_char * 8),
    ]


class _DirpRjpegVersion(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("rjpeg", ctypes.c_uint32),
        ("header", ctypes.c_uint32),
        ("curve", ctypes.c_uint32),
    ]


class _DirpResolution(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
    ]


class _DirpMeasurementParams(ctypes.Structure):
    _pack_ = 1
    # Modern DJI TSDK ABI (including 1.8) adds ambient_temp after reflection.
    # Keeping the exact field order is required for ctypes/C ABI compatibility.
    _fields_ = [
        ("distance", ctypes.c_float),
        ("humidity", ctypes.c_float),
        ("emissivity", ctypes.c_float),
        ("reflection", ctypes.c_float),
        ("ambient_temp", ctypes.c_float),
    ]


class _FloatRange(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("min", ctypes.c_float),
        ("max", ctypes.c_float),
    ]


class _DirpMeasurementParamsRangeLegacy(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("distance", _FloatRange),
        ("humidity", _FloatRange),
        ("emissivity", _FloatRange),
        ("reflection", _FloatRange),
    ]


class _DirpMeasurementParamsRangeV2(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("distance", _FloatRange),
        ("humidity", _FloatRange),
        ("emissivity", _FloatRange),
        ("reflection", _FloatRange),
        ("ambient_temp", _FloatRange),
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
        self._measurement_abi = self._detect_measurement_abi()
        self._api_version_abi = self._detect_api_version_abi()
        self._dll_directory_handle = None
        self._helper_libraries: list[ctypes.CDLL] = []
        self._library_path = self._dirp_library_path()
        self._library_sha256 = self._sha256_path(self._library_path)
        self._library = self._load_library()
        self._bind()

    def _header_sources(self) -> list[str]:
        search_roots: list[Path] = []
        release_dir = getattr(self, "release_dir", None)
        if isinstance(release_dir, Path):
            search_roots.extend(
                [release_dir, *list(release_dir.parents)[:5]]
            )
        search_roots.extend(
            [self.sdk_dir, *list(self.sdk_dir.parents)[:5]]
        )

        candidates: list[Path] = []
        seen_roots: set[Path] = set()
        for root in search_roots:
            try:
                resolved_root = root.resolve()
            except OSError:
                resolved_root = root
            if resolved_root in seen_roots:
                continue
            seen_roots.add(resolved_root)
            candidates.extend(
                [
                    root / "tsdk-core" / "api" / "dirp_api.h",
                    root / "api" / "dirp_api.h",
                    root / "include" / "dirp_api.h",
                    root / "dirp_api.h",
                ]
            )

        sources: list[str] = []
        seen_headers: set[Path] = set()
        for header in candidates:
            try:
                resolved = header.resolve()
            except OSError:
                resolved = header
            if resolved in seen_headers or not header.is_file():
                continue
            seen_headers.add(resolved)
            try:
                sources.append(
                    header.read_text(
                        encoding="utf-8",
                        errors="ignore",
                    )
                )
            except OSError:
                continue
        return sources

    @staticmethod
    def _single_confirmed_abi(
        values: set[str],
        *,
        label: str,
    ) -> str:
        if len(values) == 1:
            return next(iter(values))
        if len(values) > 1:
            logger.warning(
                "Conflicting DJI DIRP %s declarations found; "
                "treating ABI as UNKNOWN: %s",
                label,
                sorted(values),
            )
        return "UNKNOWN"

    def _detect_api_version_abi(self) -> str:
        handle_signature = re.compile(
            r"dirp_get_api_version\s*\(\s*DIRP_HANDLE\s+\w+\s*,\s*"
            r"dirp_api_version_t\s*\*\s*\w+\s*\)",
            re.MULTILINE,
        )
        global_signature = re.compile(
            r"dirp_get_api_version\s*\(\s*"
            r"dirp_api_version_t\s*\*\s*\w+\s*\)",
            re.MULTILINE,
        )
        detected: set[str] = set()
        for source in self._header_sources():
            if handle_signature.search(source):
                detected.add("HANDLE_V2")
            elif global_signature.search(source):
                detected.add("GLOBAL_V1")
        return self._single_confirmed_abi(
            detected,
            label="dirp_get_api_version ABI",
        )

    def _detect_measurement_abi(self) -> str:
        struct_pattern = re.compile(
            r"typedef\s+struct(?:\s+\w+)?\s*\{"
            r"(?P<body>.*?)"
            r"\}\s*dirp_measurement_params_t\s*;",
            re.DOTALL,
        )
        field_patterns = {
            field: re.compile(rf"\bfloat\s+{field}\s*;")
            for field in (
                "distance",
                "humidity",
                "emissivity",
                "reflection",
            )
        }
        ambient_pattern = re.compile(
            r"\bfloat\s+ambient_temp\s*;"
        )
        detected: set[str] = set()
        for source in self._header_sources():
            match = struct_pattern.search(source)
            if match is None:
                continue
            body = match.group("body")
            if not all(
                pattern.search(body)
                for pattern in field_patterns.values()
            ):
                continue
            detected.add(
                "AMBIENT_V2"
                if ambient_pattern.search(body)
                else "LEGACY_V1"
            )
        return self._single_confirmed_abi(
            detected,
            label="measurement ABI",
        )

    @staticmethod
    def _resolve_release_dir(root: Path) -> Path:
        if not root.exists():
            raise FileNotFoundError(f"DJI Thermal SDK directory not found: {root}")

        system = platform.system()
        library_name = "libdirp.dll" if system == "Windows" else "libdirp.so"
        direct = root / library_name
        if direct.is_file():
            return root

        candidates = sorted(
            {
                path.parent.resolve()
                for path in root.rglob(library_name)
                if (
                    "x64" in path.parent.name.lower()
                    or "x86_64" in path.parent.name.lower()
                )
            },
            key=lambda item: (len(item.parts), str(item)),
        )
        if not candidates:
            raise FileNotFoundError(
                f"{library_name} x64 release not found below DJI Thermal SDK directory: {root}"
            )
        if len(candidates) > 1:
            raise ValueError(
                "Multiple DJI Thermal SDK x64 releases found below "
                f"{root}; provide the exact SDK release directory"
            )
        return candidates[0]

    def _dirp_library_path(self) -> Path:
        system = platform.system()
        if system == "Windows":
            return self.release_dir / "libdirp.dll"
        if system == "Linux":
            return self.release_dir / "libdirp.so"
        raise NotImplementedError(
            f"DJI Thermal SDK worker does not support {system}"
        )

    @staticmethod
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_library(self) -> ctypes.CDLL:
        system = platform.system()
        library_path = self._library_path

        if system == "Windows":
            if hasattr(os, "add_dll_directory"):
                self._dll_directory_handle = os.add_dll_directory(str(self.release_dir))
            try:
                return ctypes.CDLL(str(library_path))
            except OSError as exc:
                raise OSError(
                    f"Unable to load DJI Thermal SDK from {library_path}: {exc}"
                ) from exc
        # DJI packages helper libraries beside libdirp. Preload what can be loaded
        # globally so libdirp can resolve optional codec/IR processing symbols.
        mode = getattr(ctypes, "RTLD_GLOBAL", 0)
        pending = [
            helper
            for helper in sorted(self.release_dir.glob("*.so*"))
            if helper.name != "libdirp.so"
        ]
        deferred: list[tuple[Path, OSError]] = []
        while pending:
            next_pending: list[Path] = []
            deferred = []
            loaded_any = False
            for helper in pending:
                try:
                    library = ctypes.CDLL(str(helper), mode=mode)
                    self._helper_libraries.append(library)
                    loaded_any = True
                except OSError as exc:
                    next_pending.append(helper)
                    deferred.append((helper, exc))
            if not loaded_any:
                break
            pending = next_pending

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

        self._get_api_version = getattr(
            self._library,
            "dirp_get_api_version",
            None,
        )
        if self._get_api_version is not None:
            if self._api_version_abi == "HANDLE_V2":
                self._get_api_version.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(_DirpApiVersion),
                ]
                self._get_api_version.restype = ctypes.c_int32
            elif self._api_version_abi == "GLOBAL_V1":
                self._get_api_version.argtypes = [
                    ctypes.POINTER(_DirpApiVersion),
                ]
                self._get_api_version.restype = ctypes.c_int32
            else:
                logger.warning(
                    "Skipping dirp_get_api_version because dirp_api.h did not "
                    "confirm whether this SDK uses the global or handle ABI"
                )
                self._get_api_version = None

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

        self._get_measurement_range = getattr(
            self._library,
            "dirp_get_measurement_params_range",
            None,
        )
        if self._get_measurement_range is not None and self._measurement_abi in {
            "LEGACY_V1",
            "AMBIENT_V2",
        }:
            range_type = (
                _DirpMeasurementParamsRangeV2
                if self._measurement_abi == "AMBIENT_V2"
                else _DirpMeasurementParamsRangeLegacy
            )
            self._get_measurement_range.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(range_type),
            ]
            self._get_measurement_range.restype = ctypes.c_int32
        else:
            self._get_measurement_range = None

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
            verbose.restype = None
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
        allowed = {
            "distance_m",
            "humidity_pct",
            "emissivity",
            "reflection_c",
            "ambient_temp_c",
        }
        unknown = set(result) - allowed
        if unknown:
            raise ValueError(f"Unsupported measurement overrides: {sorted(unknown)}")
        for key, value in result.items():
            if not np.isfinite(value):
                raise ValueError(f"{key} must be finite, got {value}")
        if "distance_m" in result and result["distance_m"] <= 0:
            raise ValueError("distance_m must be greater than zero")
        if "humidity_pct" in result and not 0.0 <= result["humidity_pct"] <= 100.0:
            raise ValueError("humidity_pct must be in [0, 100]")
        if "emissivity" in result and not 0.0 < result["emissivity"] <= 1.0:
            raise ValueError("emissivity must be in (0, 1]")
        return result

    @staticmethod
    def _range_dict(value: ctypes.Structure, *, include_ambient: bool) -> dict[str, dict[str, float]]:
        fields = [
            ("distance_m", "distance"),
            ("humidity_pct", "humidity"),
            ("emissivity", "emissivity"),
            ("reflection_c", "reflection"),
        ]
        if include_ambient:
            fields.append(("ambient_temp_c", "ambient_temp"))
        return {
            output: {
                "min": float(getattr(value, field).min),
                "max": float(getattr(value, field).max),
            }
            for output, field in fields
        }

    def _measurement_ranges(
        self,
        handle: ctypes.c_void_p,
    ) -> dict[str, dict[str, float]] | None:
        if self._get_measurement_range is None:
            return None
        value = (
            _DirpMeasurementParamsRangeV2()
            if self._measurement_abi == "AMBIENT_V2"
            else _DirpMeasurementParamsRangeLegacy()
        )
        code = int(self._get_measurement_range(handle, ctypes.byref(value)))
        if code in {DIRP_ERROR_UNSUPPORTED_FUNC, DIRP_ERROR_NOT_READY}:
            return None
        self._check("dirp_get_measurement_params_range", code)
        return self._range_dict(
            value,
            include_ambient=self._measurement_abi == "AMBIENT_V2",
        )

    @staticmethod
    def _validate_against_sdk_ranges(
        requested: Mapping[str, float],
        ranges: Mapping[str, Mapping[str, float]] | None,
    ) -> None:
        if not ranges:
            return
        for key, value in requested.items():
            bounds = ranges.get(key)
            if not bounds:
                continue
            minimum = float(bounds["min"])
            maximum = float(bounds["max"])
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{key}={value} is outside DJI DIRP range [{minimum}, {maximum}]"
                )

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
        if (
            "ambient_temp_c" in requested
            and self._measurement_abi != "AMBIENT_V2"
        ):
            raise ValueError(
                "ambient_temp_c override requires a DJI dirp_api.h that confirms "
                "the modern ambient_temp measurement ABI"
            )
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

            api_version: _DirpApiVersion | None = None
            if self._get_api_version is not None:
                api_version = _DirpApiVersion()
                if self._api_version_abi == "HANDLE_V2":
                    api_code = int(
                        self._get_api_version(
                            handle,
                            ctypes.byref(api_version),
                        )
                    )
                elif self._api_version_abi == "GLOBAL_V1":
                    api_code = int(
                        self._get_api_version(ctypes.byref(api_version))
                    )
                else:
                    raise RuntimeError(
                        "dirp_get_api_version was bound without a confirmed ABI"
                    )
                self._check("dirp_get_api_version", api_code)

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
            measurement_ranges = self._measurement_ranges(handle)
            self._validate_against_sdk_ranges(requested, measurement_ranges)
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
                    ambient_temp_c=(
                        float(params.ambient_temp)
                        if self._measurement_abi == "AMBIENT_V2"
                        else None
                    ),
                )
                if requested:
                    params.distance = requested.get("distance_m", measurement.distance_m)
                    params.humidity = requested.get("humidity_pct", measurement.humidity_pct)
                    params.emissivity = requested.get("emissivity", measurement.emissivity)
                    params.reflection = requested.get("reflection_c", measurement.reflection_c)
                    if "ambient_temp_c" in requested:
                        params.ambient_temp = requested["ambient_temp_c"]
                    set_code = int(
                        self._set_measurement(handle, ctypes.byref(params))
                    )
                    if set_code == DIRP_SUCCESS:
                        measurement = MeasurementParams(
                            distance_m=float(params.distance),
                            humidity_pct=float(params.humidity),
                            emissivity=float(params.emissivity),
                            reflection_c=float(params.reflection),
                            ambient_temp_c=(
                                float(params.ambient_temp)
                                if self._measurement_abi == "AMBIENT_V2"
                                else None
                            ),
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
                api_version=(
                    {
                        "api": int(api_version.api),
                        "magic": bytes(api_version.magic)
                        .split(b"\x00", 1)[0]
                        .decode("ascii", errors="replace"),
                    }
                    if api_version is not None
                    else {
                        "api": 0,
                        "magic": "UNKNOWN",
                        "query_status": "SKIPPED_UNCONFIRMED_ABI",
                    }
                ),
                rjpeg_version={
                    "rjpeg": int(version.rjpeg),
                    "header": int(version.header),
                    "curve": int(version.curve),
                },
                measurement_params=measurement,
                measurement_ranges=measurement_ranges,
                measurement_mode=measurement_mode,
                measurement_error_code=measurement_error_code,
                sdk_label=self.sdk_label,
                measurement_abi=self._measurement_abi,
                sdk_library_name=self._library_path.name,
                sdk_library_sha256=self._library_sha256,
            )
        finally:
            if created and handle.value:
                try:
                    self._destroy(handle)
                except (OSError, ctypes.ArgumentError) as exc:
                    # Never mask the primary decode exception with cleanup failure.
                    logger.warning("DJI DIRP handle cleanup failed: %s", exc)
