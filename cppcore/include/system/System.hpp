#pragma once
#include "Lattice.hpp"
#include "system/CompressedSublattices.hpp"
#include "system/HoppingBlocks.hpp"
#include "system/Generators.hpp"

#include "numeric/dense.hpp"
#include "numeric/sparse.hpp"

#include <vector>
#include <memory>

namespace cpb {

class Foundation;
class FinalizedIndices;
class TranslationalSymmetry;

/**
 Stores the positions, sublattice and hopping IDs for all lattice sites.
 */
struct System {
    struct Boundary;

    Lattice lattice;
    CartesianArray positions;
    CompressedSublattices compressed_sublattices;
    HoppingBlocks hopping_blocks;
    std::vector<Boundary> boundaries;

    System(Lattice const& lattice) : lattice(lattice) {}
    System(Foundation const& foundation, TranslationalSymmetry const& symmetry,
           HoppingGenerators const& hopping_generators);

    /// The total number of lattice sites i.e. unique positions. Note that a single site may
    /// consist of several orbitals/spins which means that the size of the Hamiltonian matrix
    /// must be >= to the number of sites. See `System::hamiltonian_size()`.
    idx_t num_sites() const { return positions.size(); }

    /// The square matrix size required to hold all the Hamiltonian terms after taking into
    /// account the number of orbitals/spins at each lattice site.
    idx_t hamiltonian_size() const;

    /// Translate the given System index into it's corresponding Hamiltonian index
    idx_t to_hamiltonian_index(idx_t system_index) const;

    /// Find the index of the site nearest to the given position. Optional: filter by sublattice.
    idx_t find_nearest(Cartesian position, string_view sublattice_name = "") const;
};

/**
 Stores sites that belong to a system boundary
 */
struct System::Boundary {
    HoppingBlocks hopping_blocks;
    Cartesian shift; ///< shift length (periodic boundary condition)
};

namespace detail {
    void populate_system(System& system, Foundation const& foundation);
    void populate_boundaries(System& system, Foundation const& foundation,
                             TranslationalSymmetry const& symmetry);
    void add_extra_hoppings(System& system, HoppingGenerator const& gen);
} // namespace detail

} // namespace cpb
