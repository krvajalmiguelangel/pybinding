#include "kpm/Strategy.hpp"

#include "kpm/starters.hpp"
#ifdef CPB_USE_CUDA
# include "cuda/kpm/calc_moments.hpp"
#endif
#include "kpm/reconstruct.hpp"

namespace cpb { namespace kpm {

namespace {
    template<class scalar_t>
    Bounds<scalar_t> reset_bounds(SparseMatrixX<scalar_t> const* hamiltonian,
                                  Config const& config) {
        if (config.min_energy == config.max_energy) {
            return {hamiltonian, config.lanczos_precision}; // will be automatically computed
        } else {
            return {config.min_energy, config.max_energy}; // user-defined bounds
        }
    }
} // anonymous namespace

template<class scalar_t>
StrategyTemplate<scalar_t>::StrategyTemplate(SparseMatrixRC<scalar_t> h, Config const& config)
    : hamiltonian(std::move(h)), config(config), bounds(reset_bounds(hamiltonian.get(), config)),
      optimized_hamiltonian(hamiltonian.get(), config.matrix_format, config.algorithm.reorder()) {
    if (config.min_energy > config.max_energy) {
        throw std::invalid_argument("KPM: Invalid energy range specified (min > max).");
    }
}

template<class scalar_t>
bool StrategyTemplate<scalar_t>::change_hamiltonian(Hamiltonian const& h) {
    if (!ham::is<scalar_t>(h)) {
        return false;
    }

    hamiltonian = ham::get_shared_ptr<scalar_t>(h);
    optimized_hamiltonian = {hamiltonian.get(), config.matrix_format, config.algorithm.reorder()};
    bounds = reset_bounds(hamiltonian.get(), config);

    return true;
}

template<class scalar_t>
ArrayXd StrategyTemplate<scalar_t>::ldos(idx_t index, ArrayXd const& energy, double broadening) {
    auto const scale = bounds.scaling_factors();
    auto const num_moments = config.kernel.required_num_moments(broadening / scale.a);

    auto& oh = optimized_hamiltonian;
    oh.optimize_for({index, index}, scale);
    oh.populate_stats(stats, num_moments, config.algorithm);

    auto moments = DiagonalMoments<scalar_t>(num_moments);

    stats.moments_timer.tic();
    compute(moments, exval_starter(oh), oh, config.algorithm);
    stats.moments_timer.toc();

    config.kernel.apply(moments.get());
    return reconstruct<real_t>(moments.get().real(), energy, scale);
}

template<class scalar_t>
ArrayXcd StrategyTemplate<scalar_t>::greens(idx_t row, idx_t col, ArrayXd const& energy,
                                            double broadening) {
    return std::move(greens_vector(row, {col}, energy, broadening).front());
}

template<class scalar_t>
std::vector<ArrayXcd>
StrategyTemplate<scalar_t>::greens_vector(idx_t row, std::vector<idx_t> const& cols,
                                          ArrayXd const& energy, double broadening) {
    assert(!cols.empty());
    auto const scale = bounds.scaling_factors();
    auto const num_moments = config.kernel.required_num_moments(broadening / scale.a);

    auto& oh = optimized_hamiltonian;
    oh.optimize_for({row, cols}, scale);
    oh.populate_stats(stats, num_moments, config.algorithm);

    if (oh.idx().is_diagonal()) {
        auto moments = DiagonalMoments<scalar_t>(num_moments);

        stats.moments_timer.tic();
        compute(moments, exval_starter(oh), oh, config.algorithm);
        stats.moments_timer.toc();

        config.kernel.apply(moments.get());
        return {reconstruct_greens(moments.get(), energy, scale)};
    } else {
        auto moments_vector = OffDiagonalMoments<scalar_t>(num_moments, oh.idx());

        stats.moments_timer.tic();
        compute(moments_vector, exval_starter(oh), oh, config.algorithm);
        stats.moments_timer.toc();

        for (auto& moments : moments_vector.get()) {
            config.kernel.apply(moments);
        }

        return transform<std::vector>(moments_vector.get(), [&](ArrayX<scalar_t> const& moments) {
            return reconstruct_greens(moments, energy, scale);
        });
    }
}

template<class scalar_t>
ArrayXd StrategyTemplate<scalar_t>::dos(ArrayXd const& energy, double broadening) {
    auto const scale = bounds.scaling_factors();
    auto const num_moments = config.kernel.required_num_moments(broadening / scale.a);

    auto specialized_algorithm = config.algorithm;
    specialized_algorithm.optimal_size = false; // not applicable for this calculation

    auto& oh = optimized_hamiltonian;
    oh.optimize_for({0, 0}, scale);
    oh.populate_stats(stats, num_moments, specialized_algorithm);

    auto moments = DiagonalMoments<scalar_t>(num_moments);
    auto total = moments.get();

    stats.multiplier = config.num_random;
    stats.moments_timer.tic();
    std::mt19937 generator;
    for (auto j = 0; j < config.num_random; ++j) {
        compute(moments, random_starter(oh, generator), oh, specialized_algorithm);
        total += moments.get();
    }
    total /= static_cast<real_t>(config.num_random);
    stats.moments_timer.toc();

    config.kernel.apply(total);
    return reconstruct<real_t>(total.real(), energy, scale);
}

template<class scalar_t>
std::string StrategyTemplate<scalar_t>::report(bool shortform) const {
    return bounds.report(shortform)
           + stats.report(shortform)
           + (shortform ? "|" : "Total time:");
}

CPB_INSTANTIATE_TEMPLATE_CLASS(StrategyTemplate)

#ifdef CPB_USE_CUDA
struct CudaCalcMoments {
    static MatrixConfig matrix_config(int opt_level) {
        switch (opt_level) {
            case 0: return {MatrixConfig::Reorder::OFF, MatrixConfig::Format::ELL};
            default: return {MatrixConfig::Reorder::ON, MatrixConfig::Format::ELL};
        }
    };

    template<class scalar_t>
    static MomentsMatrix<scalar_t> moments_vector(OptimizedHamiltonian<scalar_t> const& oh,
                                                  int num_moments, int opt_level) {
        switch (opt_level) {
            default: return calc_moments2(oh.ell(), oh.idx(), num_moments, oh.sizes());
        }
    }

    template<class scalar_t>
    static ArrayX<scalar_t> moments_diag(OptimizedHamiltonian<scalar_t> const& oh,
                                         int num_moments, int opt_level) {
        assert(oh.idx().is_diagonal());
        using Cuda = cuda::I<scalar_t>;
        auto const i = oh.idx().row;
        auto const ell = ellref(oh.ell());

        auto moments = [&]{
            switch (opt_level) {
                case 0: return Cuda::calc_diag_moments0(ell, i, num_moments);
                default: return Cuda::calc_diag_moments1(ell, i, num_moments, oh.sizes());
            }
        }();
        return eigen_cast<ArrayX>(moments);
    }
};

CPB_INSTANTIATE_TEMPLATE_CLASS_VARGS(StrategyTemplate, CudaCalcMoments)
#endif // CPB_USE_CUDA

}} // namespace cpb::kpm
