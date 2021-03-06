"""Computations based on Chebyshev polynomial expansion

The kernel polynomial method (KPM) can be used to approximate various functions by expanding them
in a series of Chebyshev polynomials.
"""
import numpy as np
import scipy

from . import _cpp
from . import results
from .model import Model
from .system import System
from .utils.time import timed

__all__ = ['KernelPolynomialMethod', 'kpm', 'kpm_cuda', 'jackson_kernel', 'lorentz_kernel']


class KernelPolynomialMethod:
    """The common interface for various KPM implementations

    It should not be created directly but via specific functions
    like :func:`kpm` or :func:`kpm_cuda`.
    """

    def __init__(self, impl):
        self.impl = impl

    @property
    def model(self) -> Model:
        """The tight-binding model holding the Hamiltonian"""
        return self.impl.model

    @model.setter
    def model(self, model):
        self.impl.model = model

    @property
    def system(self) -> System:
        """The tight-binding system (shortcut for `KernelPolynomialMethod.model.system`)"""
        return System(self.impl.system)

    def report(self, shortform=False):
        """Return a report of the last computation

        Parameters
        ----------
        shortform : bool, optional
            Return a short one line version of the report
        """
        return self.impl.report(shortform)

    def __call__(self, *args, **kwargs):
        """Deprecated"""  # TODO: remove
        return self.calc_greens(*args, **kwargs)

    def calc_greens(self, i, j, energy, broadening):
        """Calculate Green's function of a single Hamiltonian element

        Parameters
        ----------
        i, j : int
            Hamiltonian indices.
        energy : ndarray
            Energy value array.
        broadening : float
            Width, in energy, of the smallest detail which can be resolved.
            Lower values result in longer calculation time.

        Returns
        -------
        ndarray
            Array of the same size as the input `energy`.
        """
        return self.impl.calc_greens(i, j, energy, broadening)

    def calc_ldos(self, energy, broadening, position, sublattice=""):
        """Calculate the local density of states as a function of energy

        Parameters
        ----------
        energy : ndarray
            Values for which the LDOS is calculated.
        broadening : float
            Width, in energy, of the smallest detail which can be resolved.
            Lower values result in longer calculation time.
        position : array_like
            Cartesian position of the lattice site for which the LDOS is calculated.
            Doesn't need to be exact: the method will find the actual site which is
            closest to the given position.
        sublattice : str
            Only look for sites of a specific sublattice, closest to `position`.
            The default value considers any sublattice.

        Returns
        -------
        :class:`~pybinding.LDOS`
        """
        ldos = self.impl.calc_ldos(energy, broadening, position, sublattice)
        return results.LDOS(energy, ldos)

    def calc_dos(self, energy, broadening):
        """Calculate the density of states as a function of energy

        Parameters
        ----------
        energy : ndarray
            Values for which the DOS is calculated.
        broadening : float
            Width, in energy, of the smallest detail which can be resolved.
            Lower values result in longer calculation time.

        Returns
        -------
        :class:`~pybinding.DOS`
        """
        dos = self.impl.calc_dos(energy, broadening)
        return results.DOS(energy, dos)

    def deferred_ldos(self, energy, broadening, position, sublattice=""):
        """Same as :meth:`calc_ldos` but for parallel computation: see the :mod:`.parallel` module

        Parameters
        ----------
        energy : ndarray
            Values for which the LDOS is calculated.
        broadening : float
            Width, in energy, of the smallest detail which can be resolved.
            Lower values result in longer calculation time.
        position : array_like
            Cartesian position of the lattice site for which the LDOS is calculated.
            Doesn't need to be exact: the method will find the actual site which is
            closest to the given position.
        sublattice : str
            Only look for sites of a specific sublattice, closest to `position`.
            The default value considers any sublattice.

        Returns
        -------
        Deferred
        """
        return self.impl.deferred_ldos(energy, broadening, position, sublattice)


def kpm(model, energy_range=None, kernel="default", num_random=1, **kwargs):
    """The default CPU implementation of the Kernel Polynomial Method

    This implementation works on any system and is well optimized.

    Parameters
    ----------
    model : Model
        Model which will provide the Hamiltonian matrix.
    energy_range : Optional[Tuple[float, float]]
        KPM needs to know the lowest and highest eigenvalue of the Hamiltonian, before
        computing the expansion moments. By default, this is determined automatically
        using a quick Lanczos procedure. To override the automatic boundaries pass a
        `(min_value, max_value)` tuple here. The values can be overestimated, but note
        that performance drops as the energy range becomes wider. On the other hand,
        underestimating the range will produce `NaN` values in the results.
    kernel : Kernel
        The kernel in the *Kernel* Polynomial Method. Used to improve the quality of
        the function reconstructed from the Chebyshev series. Possible values are
        :func:`jackson_kernel` or :func:`lorentz_kernel`. The Lorentz kernel is used
        by default with `lambda = 4`.
    num_random : int
        The number of random vectors to use for stochastic KPM calculations (e.g. DOS).

    Returns
    -------
    :class:`~pybinding.chebyshev.KernelPolynomialMethod`
    """
    if kernel == "default":
        kernel = lorentz_kernel()
    return KernelPolynomialMethod(_cpp.kpm(model, energy_range or (0, 0), kernel,
                                           num_random=num_random, **kwargs))


def kpm_cuda(model, energy_range=None, kernel="default", **kwargs):
    """Same as :func:`kpm` except that it's executed on the GPU using CUDA (if supported)

    See :func:`kpm` for detailed parameter documentation.
    This method is only available if the C++ extension module was compiled with CUDA.

    Parameters
    ----------
    model : Model
    energy_range : Optional[Tuple[float, float]]
    kernel : Kernel

    Returns
    -------
    :class:`~pybinding.chebyshev.KernelPolynomialMethod`
    """
    try:
        if kernel == "default":
            kernel = lorentz_kernel()
        # noinspection PyUnresolvedReferences
        return KernelPolynomialMethod(_cpp.kpm_cuda(model, energy_range or (0, 0),
                                                    kernel, **kwargs))
    except AttributeError:
        raise Exception("The module was compiled without CUDA support.\n"
                        "Use a different KPM implementation or recompile the module with CUDA.")


def jackson_kernel():
    """The Jackson kernel -- a good general-purpose kernel, appropriate for most applications

    Imposes Gaussian broadening `sigma = pi / N` where `N` is the number of moments. The
    broadening value is user-defined for each function calculation (LDOS, Green's, etc.).
    The number of moments is then determined based on the broadening -- it's not directly
    set by the user.
    """
    return _cpp.jackson_kernel()


def lorentz_kernel(lambda_value=4.0):
    """The Lorentz kernel -- best for Green's function

    This kernel is most appropriate for the expansion of the Green’s function because it most
    closely mimics the divergences near the true eigenvalues of the Hamiltonian. The Lorentzian
    broadening is given by `epsilon = lambda / N` where `N` is the number of moments.

    Parameters
    ----------
    lambda_value : float
        May be used to fine-tune the smoothness of the convergence. Usual values are
        between 3 and 5. Lower values will speed up the calculation at the cost of
        accuracy. If in doubt, leave it at the default value of 4.
    """
    return _cpp.lorentz_kernel(lambda_value)


class _PythonImpl:
    """Basic Python/SciPy implementation of KPM"""

    def __init__(self, model, energy_range, kernel, **_):
        self.model = model
        self.energy_range = energy_range
        self.kernel = kernel

        self._stats = {}

    @property
    def stats(self):
        class AttrDict(dict):
            """Allows dict items to be retrieved as attributes: d["item"] == d.item"""
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.__dict__ = self

        s = AttrDict(self._stats)
        s.update({k: v.elapsed for k, v in s.items() if "_time" in k})
        s["eps"] = s["nnz"] / s["moments_time"]
        return s

    def _scaling_factors(self):
        """Compute the energy bounds of the model and return the appropriate KPM scaling factors"""
        def find_bounds():
            if self.energy_range[0] != self.energy_range[1]:
                return self.energy_range

            from scipy.sparse.linalg import eigsh
            h = self.model.hamiltonian
            self.energy_range = [eigsh(h, which=x, k=1, tol=2e-3, return_eigenvectors=False)[0]
                                 for x in ("SA", "LA")]
            return self.energy_range

        with timed() as self._stats["bounds_time"]:
            emin, emax = find_bounds()
        self._stats["energy_min"] = emin
        self._stats["energy_max"] = emax

        tolerance = 0.01
        a = 0.5 * (emax - emin) * (1 + tolerance)
        b = 0.5 * (emax + emin)
        return a, b

    def _rescale_hamiltonian(self, h, a, b):
        size = h.shape[0]
        with timed() as self._stats["rescale_time"]:
            return (h - b * scipy.sparse.eye(size)) * (2 / a)

    def _compute_diagonal_moments(self, num_moments, starter, h2):
        """Procedure for computing KPM moments when the two vectors are identical"""
        r0 = starter.copy()
        r1 = h2.dot(r0) * 0.5

        moments = np.zeros(num_moments, dtype=h2.dtype)
        moments[0] = np.vdot(r0, r0) * 0.5
        moments[1] = np.vdot(r1, r0)

        for n in range(1, num_moments // 2):
            r0 = h2.dot(r1) - r0
            r0, r1 = r1, r0
            moments[2 * n] = 2 * (np.vdot(r0, r0) - moments[0])
            moments[2 * n + 1] = 2 * np.vdot(r1, r0) - moments[1]

        self._stats["num_moments"] = num_moments
        self._stats["nnz"] = h2.nnz * num_moments / 2
        self._stats["vector_memory"] = r0.nbytes + r1.nbytes
        self._stats["matrix_memory"] = (h2.data.nbytes + h2.indices.nbytes + h2.indptr.nbytes
                                        if isinstance(h2, scipy.sparse.csr_matrix) else 0)
        return moments

    @staticmethod
    def _exval_starter(h2, index):
        """Initial vector for the expectation value procedure"""
        r0 = np.zeros(h2.shape[0], dtype=h2.dtype)
        r0[index] = 1
        return r0

    @staticmethod
    def _reconstruct_real(moments, energy, a, b):
        """Reconstruct a real function from KPM moments"""
        scaled_energy = (energy - b) / a
        ns = np.arange(moments.size)
        k = 2 / (a * np.pi)
        return np.array([k / np.sqrt(1 - w**2) * np.sum(moments.real * np.cos(ns * np.arccos(w)))
                         for w in scaled_energy])

    def _ldos(self, index, energy, broadening):
        """Calculate the LDOS at the given Hamiltonian index"""
        a, b = self._scaling_factors()
        num_moments = self.kernel.required_num_moments(broadening / a)
        h2 = self._rescale_hamiltonian(self.model.hamiltonian, a, b)

        starter = self._exval_starter(h2, index)
        with timed() as self._stats["moments_time"]:
            moments = self._compute_diagonal_moments(num_moments, starter, h2)

        with timed() as self._stats["reconstruct_time"]:
            moments *= self.kernel.damping_coefficients(num_moments)
            return self._reconstruct_real(moments, energy, a, b)

    def calc_ldos(self, energy, broadening, position, sublattice=""):
        """Calculate the LDOS at the given position/sublattice"""
        with timed() as self._stats["total_time"]:
            index = self.model.system.find_nearest(position, sublattice)
            return self._ldos(index, energy, broadening)

    def report(self, *_):
        from .utils import with_suffix, pretty_duration

        stats = self.stats.copy()
        stats.update({k: with_suffix(stats[k]) for k in ("num_moments", "eps")})
        stats.update({k: pretty_duration(v) for k, v in stats.items() if "_time" in k})

        fmt = " ".join([
            "{energy_min:.2f}, {energy_max:.2f} [{bounds_time}]",
            "[{rescale_time}]",
            "{num_moments} @ {eps}eps [{moments_time}]",
            "[{reconstruct_time}]",
            "| {total_time}"
        ])
        return fmt.format_map(stats)


def kpm_python(model, energy_range=None, kernel="default", **kwargs):
    """Basic Python/SciPy implementation of KPM"""
    if kernel == "default":
        kernel = lorentz_kernel()
    return KernelPolynomialMethod(_PythonImpl(model, energy_range or (0, 0), kernel, **kwargs))
