import pytest

from tn_schemematch import load_kb
from tn_schemematch.attributes import default_spec
from tn_schemematch.personas import PersonaSet, load_personas


@pytest.fixture(scope="session")
def spec():
    return default_spec()


@pytest.fixture(scope="session")
def kb():
    return load_kb()


@pytest.fixture(scope="session")
def personas():
    return load_personas()


@pytest.fixture(scope="session")
def sample_personas(personas):
    """A deterministic slice of the benchmark, for tests that cost real time per persona.

    Some of these tests run an entire elicitation interview — up to forty questions, each
    one re-ranked against every scheme in the KB. At five personas and ten schemes that was
    free. At 247 personas and 42 schemes it is minutes per test, and a suite nobody waits
    for is a suite nobody runs.

    The slice is not random: it takes every hand-written persona (the five seeds, the
    targeted personas that close the coverage gaps, and both halves of every minimal pair)
    and every eighth sampled one. So the cases chosen *because* they are awkward are all
    kept, and only the archetype samples — which are drawn from the same distributions as
    each other — are thinned. The full set is still swept by the experiment runner, where
    the cost buys a result rather than a green tick.
    """
    chosen = {
        p.id: p for p in personas
        if not p.id.startswith("g") or int(p.id[1:]) % 8 == 1
    }
    return PersonaSet(chosen, personas.spec)
