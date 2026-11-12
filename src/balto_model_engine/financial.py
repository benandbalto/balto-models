"""Reusable financial declarations; all math remains engine expressions."""

from . import Dimension, Item, Model, if_, previous, ref, round_to, sum_over


def minimum(left, right):
    return if_(left <= right, left, right)


def maximum(left, right):
    return if_(left >= right, left, right)


def operating_noi(model: Model, *, revenue: str, expenses: str, dims=("month",)):
    """Shared monthly operating bridge for acquisition, rehab and budget inputs."""
    model.calc("operations.noi", unit="USD", dims=dims, expr=ref(revenue) - ref(expenses))


def fixed_rate_payment(model: Model, *, prefix: str, amount: str, annual_rate: str, term: int,
                       rounding_places=2):
    """Level payment by annuity present value; handles zero rates without a branch.

    The term is a structural dimension. This needs no new engine expression or
    second numeric implementation: the discount factors recur in the engine.
    """
    dim = prefix + "_payment_period"
    model.dimension(Dimension(dim, [Item(i) for i in range(1, term + 1)]))
    model.calc(prefix + ".discount", unit="ratio", dims=(dim,),
               expr=previous(prefix + ".discount", dim,
                             initial=1 / (1 + ref(annual_rate) / 12),
                             step=lambda p: p / (1 + ref(annual_rate) / 12)))
    payment = ref(amount) / sum_over(dim, ref(prefix + ".discount"))
    model.calc(prefix + ".payment", unit="USD",
               expr=payment if rounding_places is None else round_to(payment, rounding_places))
