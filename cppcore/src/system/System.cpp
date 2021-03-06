#include "system/System.hpp"

#include "system/Foundation.hpp"
#include "system/Symmetry.hpp"

namespace cpb {

System::System(Foundation const& foundation, TranslationalSymmetry const& symmetry,
               HoppingGenerators const& hopping_generators)
    : lattice(foundation.get_lattice()) {
    detail::populate_system(*this, foundation);
    if (symmetry) {
        detail::populate_boundaries(*this, foundation, symmetry);
    }

    for (auto const& gen : hopping_generators) {
        detail::add_extra_hoppings(*this, gen);
    }

    if (num_sites() == 0) { throw std::runtime_error{"Impossible system: 0 sites"}; }
}

idx_t System::hamiltonian_size() const {
    auto result = idx_t{0};
    for (auto const& sub : compressed_sublattices) {
        result += sub.ham_size();
    }
    return result;
}

idx_t System::to_hamiltonian_index(idx_t system_index) const {
    for (auto const& sub : compressed_sublattices) {
        if (sub.sys_start() <= system_index && system_index < sub.sys_end()) {
            return sub.ham_start() + (system_index - sub.sys_start()) * sub.num_orbitals();
        }
    }
    throw std::runtime_error("to_hamiltonian_index: this should never happen");
}

idx_t System::find_nearest(Cartesian target_position, string_view sublattice_name) const {
    auto const range = [&]{
        struct Range { idx_t start, end; };

        if (sublattice_name.empty()) {
            // Check all sites
            return Range{0, num_sites()};
        } else {
            // Only check sites belonging to the target sublattice
            auto const target_id = lattice[sublattice_name].alias_id;
            auto const it = std::find_if(
                compressed_sublattices.begin(), compressed_sublattices.end(),
                [&](CompressedSublattices::It const& sub) { return sub.alias_id() == target_id; }
            );
            if (it == compressed_sublattices.end()) {
                throw std::runtime_error("System::find_nearest() This should never happen");
            }

            return Range{it->sys_start(), it->sys_end()};
        }
    }();

    auto nearest_index = range.start;
    auto min_distance = (positions[range.start] - target_position).norm();

    for (auto i = range.start + 1; i < range.end; ++i) {
        auto const distance = (positions[i] - target_position).norm();
        if (distance < min_distance) {
            min_distance = distance;
            nearest_index = i;
        }
    }

    return nearest_index;
}

namespace detail {

void populate_system(System& system, Foundation const& foundation) {
    auto const& lattice = foundation.get_lattice();
    auto const& finalized_indices = foundation.get_finalized_indices();

    auto const size = finalized_indices.size();
    system.positions.resize(size);
    system.hopping_blocks = {size, lattice.hop_name_map()};
    system.hopping_blocks.reserve(finalized_indices.max_hoppings_per_family());

    for (auto const& site : foundation) {
        auto const index = finalized_indices[site];
        if (index < 0) { continue; } // invalid site

        system.positions[index] = site.get_position();
        system.compressed_sublattices.add(site.get_alias_id(), site.get_norb());

        site.for_each_neighbor([&](Site neighbor, Hopping hopping) {
            auto const neighbor_index = finalized_indices[neighbor];
            if (neighbor_index < 0) { return; } // invalid neighbor

            if (!hopping.is_conjugate) { // only make half the matrix, other half is the conjugate
                system.hopping_blocks.add(hopping.family_id, index, neighbor_index);
            }
        });
    }
    system.compressed_sublattices.verify(size);
}

void populate_boundaries(System& system, Foundation const& foundation,
                         TranslationalSymmetry const& symmetry) {
    auto const& lattice = foundation.get_lattice();
    auto const& finalized_indices = foundation.get_finalized_indices();
    auto const size = finalized_indices.size();

    for (const auto& translation : symmetry.translations(foundation)) {
        auto boundary = System::Boundary();
        boundary.shift = translation.shift_lenght;
        boundary.hopping_blocks = {size, lattice.hop_name_map()};

        for (auto const& site : foundation[translation.boundary_slice]) {
            auto const index = finalized_indices[site];
            if (index < 0) { continue; }

            // The site is shifted to the opposite edge of the translation unit
            auto const shifted_site = site.shifted(translation.shift_index);
            shifted_site.for_each_neighbor([&](Site neighbor, Hopping hopping) {
                auto const neighbor_index = finalized_indices[neighbor];
                if (neighbor_index < 0) { return; }

                boundary.hopping_blocks.add(hopping.family_id, index, neighbor_index);
            });
        }

        if (boundary.hopping_blocks.nnz() > 0) {
            system.boundaries.push_back(std::move(boundary));
        }
    }
}

void add_extra_hoppings(System& system, HoppingGenerator const& gen) {
    auto const& lattice = system.lattice;
    auto const sublattices = system.compressed_sublattices.decompressed();
    auto const family_id = lattice.hopping_family(gen.name).family_id;
    auto pairs = gen.make(system.positions, {sublattices, lattice.sub_name_map()});
    system.hopping_blocks.append(family_id, std::move(pairs.from), std::move(pairs.to));
}

} // namespace detail
} // namespace cpb
