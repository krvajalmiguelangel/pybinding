from collections import OrderedDict

import numpy as np
import matplotlib.pyplot as plt

import _pybinding
from . import pltutils
from .support.pickle import pickleable

__all__ = ['Lattice', 'make_lattice', 'square']


@pickleable(props='sublattices hopping_energies min_neighbors')
class Lattice(_pybinding.Lattice):
    def __init__(self, v1, v2=None, v3=None):
        super().__init__(*(v for v in [v1, v2, v3] if v is not None))
        self.sublattice_ids = OrderedDict()  # indexed by sublattice name
        self.hopping_ids = {}  # indexed by hopping name

    def __getitem__(self, key):
        """Get sublattice ID from name."""
        if isinstance(key, str):
            if key not in self.sublattice_ids:
                raise KeyError("There is no sublattice named '{}'".format(key))
            return self.sublattice_ids[key]
        else:  # an ID was given instead of a name, verify it
            if key not in self.sublattice_ids.values():
                raise KeyError("There is no sublattice with ID = {}".format(key))
            return key

    def register_hopping_energies(self, mapping: dict):
        for name, energy in mapping.items():
            if name in self.hopping_ids:
                raise KeyError("Hopping '{}' already exists".format(name))
            self.hopping_ids[name] = super()._register_hopping_energy(energy)

    def add_one_sublattice(self, name, offset, onsite_potential=0.0, alias=None):
        if name in self.sublattice_ids:
            raise KeyError("Sublattice '{}' already exists".format(name))

        alias = self.__getitem__(alias) if alias is not None else -1
        self.sublattice_ids[name] = super()._add_sublattice(offset, onsite_potential, alias)

    def add_sublattices(self, *sublattices):
        for sub in sublattices:
            self.add_one_sublattice(*sub)

    def add_one_hopping(self, relative_index, from_sublattice, to_sublattice, energy):
        from_sub, to_sub = map(self.__getitem__, (from_sublattice, to_sublattice))
        if energy in self.hopping_ids:
            super()._add_registered_hopping(relative_index, from_sub, to_sub,
                                            self.hopping_ids[energy])
        elif not isinstance(energy, str):
            super()._add_hopping(relative_index, from_sub, to_sub, energy)
        else:
            raise KeyError("There is no hopping named '{}'".format(energy))

    def add_hoppings(self, *hoppings):
        for hop in hoppings:
            self.add_one_hopping(*hop)

    def add_hopping_matrices(self, *pairs):
        for relative_index, matrix in pairs:
            for (from_sub, to_sub), hopping_energy in np.ndenumerate(matrix):
                if hopping_energy == 0:
                    continue
                # only consider lower triangle values of the relative_index==(0, 0) matrix
                # the upper triangle is implied via Hermitian conjugation
                if all(v == 0 for v in relative_index) and from_sub >= to_sub:
                    continue

                self.add_one_hopping(relative_index, from_sub, to_sub, hopping_energy)

    def plot_vectors(self, position):
        """Plot lattice vectors in xy plane"""
        vnorm = np.average([np.linalg.norm(v) for v in self.vectors])
        for i, vector in enumerate(self.vectors):
            v2d = vector[:2]
            if np.allclose(v2d, [0, 0]):
                continue  # nonzero only in z dimension, but the plot is 2D

            plt.arrow(position[0], position[1], *v2d, color='black', alpha=0.8,
                      head_width=vnorm / 12, head_length=vnorm / 5, length_includes_head=True)
            pltutils.annotate_box(r"$v_{}$".format(i+1), position[:2] + v2d / 2,
                                  fontcolor='white', fontsize='large')

    def plot(self, vector_position='center', **kwargs):
        # plot the primitive cell and it's neighbors (using a model... kind of meta)
        import pybinding as pb
        model = pb.Model(self, pb.symmetry.translational())
        model.system.plot(boundary_color=None, **kwargs)

        sub_center = sum(s.offset for s in self.sublattices) / len(self.sublattices)
        if vector_position is not None:
            self.plot_vectors(sub_center if vector_position == 'center' else vector_position)

        points = [n * v for v in self.vectors for n in (-1, 1)]  # for plot limit detection
        sub_names = list(self.sublattice_ids.keys())
        overlap = any(np.allclose(sub_center[:2], s.offset[:2]) for s in self.sublattices)

        for sub in self.sublattices:
            # annotate sublattice names
            pltutils.annotate_box(sub_names[sub.alias], xy=sub.offset[:2])

            for hop in sub.hoppings:
                # annotate neighboring cell indices
                if tuple(hop.relative_index[:2]) == (0, 0):
                    continue  # skip the original cell

                offset = sum(r * v for r, v in zip(hop.relative_index, self.vectors))
                points += (0.5 * r * v + offset for r, v in zip(hop.relative_index, self.vectors))

                mul = 1.2 if overlap else 1  # prevent text from overlapping with site
                xy = offset[:2] * mul + sub_center[:2]
                pltutils.annotate_box("{}, {}".format(*hop.relative_index[:2]), xy=xy)

        x, y, _ = zip(*points)
        pltutils.set_min_range(abs(max(x) - min(x)), 'x')
        pltutils.set_min_range(abs(max(y) - min(y)), 'y')


def make_lattice(vectors, sublattices, hoppings, min_neighbors=1):
    lat = Lattice(*vectors)
    lat.add_sublattices(*sublattices)
    lat.add_hoppings(*hoppings)
    lat.min_neighbors = min_neighbors
    return lat


def square(a=0.2, t=1):
    lat = Lattice([a, 0], [0, a])
    lat.add_one_sublattice('s', (0, 0))
    lat.add_hoppings(
        [(0,  1), 's', 's', t],
        [(1,  0), 's', 's', t],
        [(1,  1), 's', 's', t],
        [(1, -1), 's', 's', t],
    )
    return lat
