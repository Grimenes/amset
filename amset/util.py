import collections
import copy
import logging
import sys
from typing import Any, Dict

import numpy as np
from monty.serialization import dumpfn, loadfn
from tqdm.auto import tqdm

__author__ = "Alex Ganose"
__maintainer__ = "Alex Ganose"
__email__ = "aganose@lbl.gov"

logger = logging.getLogger(__name__)

_bar_format = "{desc} {percentage:3.0f}%|{bar}| {elapsed}<{remaining}{postfix}"


def validate_settings(user_settings):
    from amset.constants import defaults

    settings = copy.deepcopy(defaults)
    settings.update(user_settings)

    # validate the type of some settings
    if isinstance(settings["doping"], (int, float)):
        settings["doping"] = [settings["doping"]]
    elif isinstance(settings["doping"], str):
        settings["doping"] = parse_doping(settings["doping"])

    if isinstance(settings["temperatures"], (int, float)):
        settings["temperatures"] = [settings["temperatures"]]
    elif isinstance(settings["temperatures"], str):
        settings["temperatures"] = parse_temperatures(settings["temperatures"])

    if isinstance(settings["deformation_potential"], str):
        settings["deformation_potential"] = parse_deformation_potential(
            settings["deformation_potential"]
        )
    elif isinstance(settings["deformation_potential"], list):
        settings["deformation_potential"] = tuple(settings["deformation_potential"])

    if settings["static_dielectric"] is not None:
        settings["static_dielectric"] = cast_tensor(settings["static_dielectric"])

    if settings["high_frequency_dielectric"] is not None:
        settings["high_frequency_dielectric"] = cast_tensor(
            settings["high_frequency_dielectric"]
        )

    if settings["elastic_constant"] is not None:
        settings["elastic_constant"] = cast_elastic_tensor(settings["elastic_constant"])

    settings["doping"] = np.asarray(settings["doping"], dtype=np.float)
    settings["temperatures"] = np.asarray(settings["temperatures"])

    for setting in settings:
        if setting not in defaults:
            raise ValueError("Unrecognised setting: {}".format(setting))

    return settings


def cast_tensor(tensor):
    from amset.constants import numeric_types

    if isinstance(tensor, numeric_types):
        return np.eye(3) * tensor

    tensor = np.asarray(tensor)
    if len(tensor.shape) == 1:
        return np.diag(tensor)

    if tensor.shape != (3, 3):
        raise ValueError("Unsupported tensor shape.")

    return tensor


def cast_elastic_tensor(elastic_tensor):
    from pymatgen.core.tensors import Tensor

    from amset.constants import numeric_types

    if isinstance(elastic_tensor, numeric_types):
        elastic_tensor = np.eye(6) * elastic_tensor
        elastic_tensor[([3, 4, 5], [3, 4, 5])] /= 2

    elastic_tensor = np.array(elastic_tensor)
    if elastic_tensor.shape == (6, 6):
        elastic_tensor = Tensor.from_voigt(elastic_tensor)

    if elastic_tensor.shape != (3, 3, 3, 3):
        raise ValueError(
            "Unsupported elastic tensor shape. Should be (6, 6) or (3, 3, 3, 3)."
        )

    return np.array(elastic_tensor)


def tensor_average(tensor):
    return np.average(np.linalg.eigvalsh(tensor), axis=-1)


def groupby(a, b):
    # Get argsort indices, to be used to sort a and b in the next steps
    sidx = b.argsort(kind="mergesort")
    a_sorted = a[sidx]
    b_sorted = b[sidx]

    # Get the group limit indices (start, stop of groups)
    cut_idx = np.flatnonzero(np.r_[True, b_sorted[1:] != b_sorted[:-1], True])

    # Split input array with those start, stop ones
    out = np.array(
        [a_sorted[i:j] for i, j in zip(cut_idx[:-1], cut_idx[1:])], dtype=object
    )
    return out


def write_settings_to_file(settings: Dict[str, Any], filename: str):
    """Write amset configuration settings to a formatted yaml file.

    Args:
        settings: The configuration settings.
        filename: A filename.
    """
    settings = cast_dict_list(settings)
    dumpfn(settings, filename, indent=4, default_flow_style=False)


def load_settings_from_file(filename: str) -> Dict[str, Any]:
    """Load amset configuration settings from a yaml file.

    If the settings file does not contain a required parameter, the default
    value will be added to the configuration.

    An example file is given in *amset/examples/example_settings.yaml*.

    Args:
        filename: Path to settings file.

    Returns:
        The settings, with any missing values set according to the amset defaults.
    """
    logger.info("Loading settings from: {}".format(filename))
    settings = loadfn(filename)

    return validate_settings(settings)


def cast_dict_list(d):
    from pymatgen.electronic_structure.core import Spin

    if d is None:
        return d

    new_d = {}
    for k, v in d.items():
        # cast keys
        if isinstance(k, Spin):
            k = k.name

        if isinstance(v, collections.Mapping):
            new_d[k] = cast_dict_list(v)
        else:
            # cast values
            if isinstance(v, np.ndarray):
                v = v.tolist()
            elif isinstance(v, tuple):
                v = list(v)

            new_d[k] = v
    return new_d


def cast_dict_ndarray(d):
    from pymatgen.electronic_structure.core import Spin

    if d is None:
        return d

    new_d = {}
    for k, v in d.items():
        # cast keys back to spin
        if isinstance(k, str) and k in ["up", "down"]:
            k = Spin.up if "k" == "up" else Spin.up

        if isinstance(v, collections.Mapping):
            new_d[k] = cast_dict_ndarray(v)
        else:
            # cast values
            if isinstance(v, list):
                v = np.array(v)

            new_d[k] = v
    return new_d


def parse_doping(doping_str: str):
    doping_str = doping_str.strip().replace(" ", "")

    try:
        if ":" in doping_str:
            parts = list(map(float, doping_str.split(":")))

            if len(parts) != 3:
                raise ValueError

            return np.geomspace(parts[0], parts[1], int(parts[2]))

        else:
            return np.array(list(map(float, doping_str.split(","))))

    except ValueError:
        raise ValueError("ERROR: Unrecognised doping format: {}".format(doping_str))


def parse_temperatures(temperatures_str: str):
    temperatures_str = temperatures_str.strip().replace(" ", "")

    try:
        if ":" in temperatures_str:
            parts = list(map(float, temperatures_str.split(":")))

            if len(parts) != 3:
                raise ValueError

            return np.linspace(parts[0], parts[1], int(parts[2]))

        else:
            return np.array(list(map(float, temperatures_str.split(","))))

    except ValueError:
        raise ValueError(
            "ERROR: Unrecognised temperature format: {}".format(temperatures_str)
        )


def parse_deformation_potential(deformation_pot_str: str):
    if "h5" in deformation_pot_str:
        return deformation_pot_str

    deformation_pot_str = deformation_pot_str.strip().replace(" ", "")

    try:
        parts = list(map(float, deformation_pot_str.split(",")))

        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return tuple(parts)
        else:
            raise ValueError

    except ValueError:
        raise ValueError(
            "ERROR: Unrecognised deformation potential format: "
            "{}".format(deformation_pot_str)
        )


def get_progress_bar(
    iterable=None, total=None, desc="", min_desc_width=18, prepend_pipe=True
):
    from amset.constants import output_width

    if prepend_pipe:
        desc = "    ├── " + desc

    desc += ":"

    if len(desc) < min_desc_width:
        desc += " " * (min_desc_width - len(desc))

    if iterable is not None:
        return tqdm(
            iterable=iterable,
            total=total,
            ncols=output_width,
            desc=desc,
            bar_format=_bar_format,
            file=sys.stdout,
        )
    elif total is not None:
        return tqdm(
            total=total,
            ncols=output_width,
            desc=desc,
            bar_format=_bar_format,
            file=sys.stdout,
        )
    else:
        raise ValueError("Error creating progress bar, need total or iterable")


def load_amset_data(filename):
    data = loadfn(filename)
    return cast_dict_ndarray(data)


def write_mesh_data(mesh_data, filename="mesh.h5"):
    import h5py
    from pymatgen import Structure

    with h5py.File(filename, "w") as f:

        def add_data(name, data):
            if isinstance(data, np.ndarray):
                f.create_dataset(name, data=data, compression="gzip")
            elif isinstance(data, Structure):
                f["structure"] = np.string_(data.to_json())
            elif isinstance(data, (tuple, list)):
                data = np.array(data)
                if isinstance(data[0], str):
                    data = data.astype("S")
                f.create_dataset(name, data=data)
            elif data is None:
                f.create_dataset(name, data=False)
            else:
                f.create_dataset(name, data=data)

        for key, value in mesh_data.items():
            if isinstance(value, dict):
                # dict entries are given for different spins
                for spin, spin_value in value.items():
                    key = "{}_{}".format(key, spin.name)
                    add_data(key, spin_value)
            else:
                add_data(key, value)


def load_mesh_data(filename):
    import h5py
    from pymatgen import Structure

    from amset.constants import str_to_spin

    def read_data(name, data):
        if name == "structure":
            data_str = np.string_(data[()]).decode()
            return Structure.from_str(data_str, fmt="json")
        if name == "scattering_labels":
            return data[()].astype("U13")  # decode string
        if name == "vb_idx":
            d = data[()]
            return d if d is not False else None
        return data[()]

    mesh_data = {}
    with h5py.File(filename, "r") as f:
        for key, value in f.items():
            if "_up" in key or "_down" in key:
                spin = str_to_spin[key.split("_")[-1]]
                key = key.replace("_{}".format(spin.name), "")
                if key not in mesh_data:
                    mesh_data[key] = {}
                mesh_data[key][spin] = read_data(key, value)
            else:
                mesh_data[key] = read_data(key, value)

    return mesh_data


def check_nbands_equal(interpolator, amset_data):
    nbands_equal = [
        amset_data.energies[s].shape[0] == interpolator.nbands[s]
        for s in amset_data.spins
    ]
    return np.all(nbands_equal)
