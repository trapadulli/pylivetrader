import pytest
import pandas as pd

from pylivetrader.errors import (
    SymbolNotFound,
    OrderDuringInitialize,
    TradingControlViolation,
)
import pylivetrader.protocol as proto
from pylivetrader.misc import events
from pylivetrader.algorithm import Algorithm
from pylivetrader.executor.executor import AlgorithmExecutor
from pylivetrader.misc.api_context import LiveTraderAPI
from pylivetrader.loader import get_functions


def get_algo(script):
    functions = get_functions(script)
    return Algorithm(backend='pylivetrader.testing.fixtures', **functions)


def simulate_init_and_handle(algo):

    algo._assets_from_source = \
        algo.asset_finder.retrieve_all(algo.asset_finder.sids)

    if not algo.initialized:
        algo.initialize()
        algo.initialized = True

    algo.executor = AlgorithmExecutor(algo, algo.data_portal)

    dt_to_use = pd.Timestamp(
        '2018/08/13 9:30', tz='America/New_York').tz_convert('UTC')

    with LiveTraderAPI(algo):
        algo.on_dt_changed(dt_to_use)

        algo.executor.current_data.datetime = dt_to_use

        algo.before_trading_start(algo.executor.current_data)

        algo.handle_data(algo.executor.current_data)


def test_algorithm_init():
    # check init
    algo = Algorithm(backend='pylivetrader.testing.fixtures')
    assert not algo.initialized

    algo = get_algo('''
def initialize(ctx):
    pass

def handle_data(ctx, data):
    pass
    ''')

    simulate_init_and_handle(algo)


def test_algorithm_get_datetime():
    # check init
    algo = Algorithm(backend='pylivetrader.testing.fixtures')
    assert not algo.initialized

    algo = get_algo('''
import pandas as pd

def initialize(ctx):
    pass

def handle_data(ctx, data):
    dt = get_datetime()
    assert dt == pd.Timestamp(
        '2018/08/13 9:30', tz='America/New_York').tz_convert('UTC')
    ''')

    simulate_init_and_handle(algo)


def test_before_trading_start():
    # check init
    algo = Algorithm(backend='pylivetrader.testing.fixtures')
    assert not algo.initialized

    algo = get_algo('''
def before_trading_start(ctx, data):
    record(value=1)
    ''')

    simulate_init_and_handle(algo)

    assert algo.recorded_vars['value'] == 1


def test_datetime_bad_params():
    algo = get_algo("""
from pytz import timezone

def initialize(context):
    pass

def handle_data(context, data):
    get_datetime(timezone)
""")
    with pytest.raises(TypeError):
        simulate_init_and_handle(algo)


def test_schedule():
    algo = get_algo("""

def scheduled(context, data):
    pass

def initialize(context):
    schedule_function(
        scheduled,
        date_rules.every_day(),
        time_rules.market_open(minutes=1)
    )
""")

    simulate_init_and_handle(algo)

    assert algo.event_manager._events[-1].callback.__name__ == 'scheduled'
    assert isinstance(algo.event_manager._events[-1].rule, events.OncePerDay)


def test_asset_lookup():

    algo = get_algo("""
def initialize(context):
    assert symbol('ASSET1').sid == 'asset-1'
""")

    simulate_init_and_handle(algo)

    algo = get_algo("""
def initialize(context):
    symbol('INVALID')
""")
    with pytest.raises(SymbolNotFound):
        simulate_init_and_handle(algo)

    with pytest.raises(TypeError):
        algo.symbol(1)

    with pytest.raises(TypeError):
        algo.symbol((1,))

    with pytest.raises(TypeError):
        algo.symbol([1])

    with pytest.raises(TypeError):
        algo.symbol({1})

    with pytest.raises(TypeError):
        algo.symbol({"foo": "bar"})


@pytest.mark.parametrize('func, amt, expect', [
    ('order', 1, 1),
    ('order_value', 1, 1),
    ('order_target', 1, 1),
    ('order_percent', 0.1, 1),
    ('order_percent', 0.2, 2),
    ('order_target_percent', 0.1, 1),
    ('order_target_value', 1, 1),
])
def test_order(func, amt, expect):

    algo = get_algo('')

    simulate_init_and_handle(algo)

    target = algo.sid('asset-1')

    def assert_order(asset, amount, style):
        assert asset == target
        assert amount == expect

    class portfolio:
        portfolio_value = 1000.0
        positions = proto.Positions()

    algo._backend.portfolio = portfolio()

    algo._backend.order = assert_order

    getattr(algo, func)(target, amt)


def test_order_in_init():
    """
    Test that calling order in initialize
    will raise an error.
    """
    with pytest.raises(OrderDuringInitialize):
        algo = get_algo('''
def initialize(ctx):
    order(sid('asset-1'), 1)
        ''')
        simulate_init_and_handle(algo)


def test_portfolio_in_init():
    """
    Test that accessing portfolio in init doesn't break.
    """
    algo = get_algo('''
def initialize(ctx):
    ctx.portfolio
    ''')

    algo._backend.portfolio = {}

    simulate_init_and_handle(algo)


def test_account_in_init():
    """
    Test that accessing portfolio in init doesn't break.
    """
    algo = get_algo('''
def initialize(ctx):
    ctx.account
    ''')

    algo._backend.account = {}

    simulate_init_and_handle(algo)


def test_long_only():

    algo = get_algo('''
def initialize(ctx):
    set_long_only()
    ''')

    simulate_init_and_handle(algo)

    class portfolio:
        portfolio_value = 1000.0
        positions = proto.Positions()

    class order:
        id = 'oid'

    algo._backend.portfolio = portfolio
    algo._backend.order = lambda *args, **kwrags: order()

    with pytest.raises(TradingControlViolation):
        algo.order(algo.sid('asset-1'), -1)

    algo.order(algo.sid('asset-1'), 1)
