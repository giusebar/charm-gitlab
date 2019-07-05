"""Test deployment and configuration of GitLab."""
import asyncio
import os
import stat

import pytest

# Treat all tests as coroutines
pytestmark = [pytest.mark.asyncio]

juju_repository = os.getenv("JUJU_REPOSITORY", ".").rstrip("/")
series = [
    "bionic",
    # cosmic packages don't exist for gitlab, so testing is pointless
    # pytest.param('cosmic', marks=pytest.mark.xfail(reason='canary')),
]
sources = [
    ("local", "{}/builds/gitlab".format(juju_repository)),
    # stub out until a version supporting postgres is on the store ("jujucharms", "cs:~pirate-charmers/gitlab"),
]


# Custom fixtures
@pytest.fixture(params=series)
def series(request):
    """Return the series of the deployed application being tested."""
    return request.param


@pytest.fixture(params=sources, ids=[s[0] for s in sources])
def source(request):
    """Return the source of the app in test."""
    return request.param


@pytest.fixture
async def app(model, series, source):
    """Return the Juju application for the current test."""
    app_name = "gitlab-{}-{}".format(series, source[0])
    return model.applications[app_name]


async def test_gitlab_deploy(model, series, source, request):
    """Start the deploy of the GitLab charm across supported series."""
    application_name = "gitlab-{}-{}".format(series, source[0])
    cmd = "juju deploy {} -m {} --series {} {}".format(
        source[1], model.info.name, series, application_name
    )
    if request.node.get_closest_marker("xfail"):
        cmd += " --force"
    await asyncio.create_subprocess_shell(cmd)

    app = await model._wait_for_new("application", application_name)
    await model.block_until(lambda: app.status == "waiting")


async def test_gitlab_deploy_status(model, app, request):
    """Wait for the deployment of GitLab to complete and test the status is blocked prior to relations."""
    unit = app.units[0]
    await model.block_until(
        lambda: unit.agent_status == "idle" or unit.agent_status == "error"
    )
    await model.block_until(lambda: app.status == "blocked" or app.status == "error")
    assert unit.agent_status != "error"
    assert app.status != "error"


async def test_redis_deploy(model, series, app, request):
    """Create a Redis deployment for testing relation to GitLab."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")

    application_name = "gitlab-redis-{}".format(series)
    cmd = "juju deploy cs:~omnivector/redis -m {} --series xenial {}".format(
        model.info.name, application_name
    )
    await asyncio.create_subprocess_shell(cmd)
    redis = await model._wait_for_new('application', application_name)
    await model.block_until(lambda: redis.status == "active" or redis.status == "error")
    assert redis.status != "error"


async def test_pgsql_deploy(model, series, app, request):
    """Create a PostgreSQL deployment for testing relation to GitLab."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")

    application_name = "gitlab-postgresql-{}".format(series)
    cmd = "juju deploy cs:postgresql -m {} --series bionic {}".format(
        model.info.name, application_name
    )
    await asyncio.create_subprocess_shell(cmd)
    sql = await model._wait_for_new('application', application_name)
    await model.block_until(lambda: sql.status == "active" or sql.status == "error")
    assert sql.status != "error"


async def test_mysql_deploy(model, series, app, request):
    """Create a MySQL deployment for testing relation to GitLab."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")

    application_name = "gitlab-mysql-{}".format(series)
    cmd = "juju deploy cs:mysql -m {} --series xenial {}".format(
        model.info.name, application_name
    )
    await asyncio.create_subprocess_shell(cmd)
    sql = await model._wait_for_new('application', application_name)
    await model.block_until(lambda: sql.status == "active" or sql.status == "error")
    assert sql.status != "error"


async def test_redis_relate(model, series, app, request):
    """Test relating Redis to GitLab."""
    application_name = 'gitlab-redis-{}'.format(series)
    redis = model.applications[application_name]
    print('Relating {} with {}'.format(app.name, 'redis'))
    await model.add_relation(
        '{}:redis'.format(app.name),
        application_name)
    await model.block_until(lambda: redis.status == "active" or redis.status == "error")
    await model.block_until(lambda: app.status == "blocked" or app.status == "error")
    assert redis.status != "error"
    assert app.status != "error"


async def test_pgsql_relate(model, series, app, request):
    """Test relating PostgreSQL to GitLab."""
    application_name = 'gitlab-postgresql-{}'.format(series)
    sql = model.applications[application_name]
    print('Relating {} with {}'.format(app.name, application_name))
    await model.add_relation(
        '{}:pgsql'.format(app.name),
        '{}:db'.format(application_name))
    print(sql)
    await model.block_until(lambda: sql.status == "active" or sql.status == "error")
    await model.block_until(lambda: app.status == "active" or app.status == "error")
    assert sql.status != "error"
    assert app.status != "error"


async def test_charm_upgrade(model, app, request):
    """Test upgrade of the juju charm store deployed GitLab to the local charm."""
    if app.name.endswith("local"):
        pytest.skip("No need to upgrade the local deploy")

    unit = app.units[0]
    await model.block_until(lambda: unit.agent_status == "idle")
    await asyncio.create_subprocess_shell(
        "juju upgrade-charm --switch={} -m {} {}".format(
            sources[0][1], model.info.name, app.name
        )
    )
    await model.block_until(
        lambda: unit.agent_status == "idle" or unit.agent_status == "error"
    )
    await model.block_until(lambda: app.status == "active" or app.status == "error")
    assert unit.agent_status != "error"
    assert app.status != "error"


async def test_reconfigure_action(app):
    """Test action execution against deployed GitLab instances for the local charm."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")
    unit = app.units[0]
    action = await unit.run_action("reconfigure")
    action = await action.wait()
    assert action.status == "completed"


async def test_run_command(app, jujutools):
    """Test command execution against deployed GitLab instances for the local charm."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")
    unit = app.units[0]
    cmd = "echo test"
    results = await jujutools.run_command(cmd, unit)
    assert results["Code"] == "0"
    assert "test" in results["Stdout"]


async def test_juju_file_stat(app, jujutools):
    """Test the ability to retrieve the status of a file from a deployed unit."""
    if app.name.endswith("jujucharms"):
        pytest.skip("No need to test the charm deploy")
    unit = app.units[0]
    path = "/var/lib/juju/agents/unit-{}/charm/metadata.yaml".format(
        unit.entity_id.replace("/", "-")
    )
    fstat = await jujutools.file_stat(path, unit)
    assert stat.filemode(fstat.st_mode) == "-rw-r--r--"
    assert fstat.st_uid == 0
    assert fstat.st_gid == 0


async def test_pgsql_unrelate(model, series, app, request):
    """Test removing PostgreSQL relation to GitLab, unit should return to blocked state."""
    application_name = 'gitlab-postgresql-{}'.format(series)
    sql = model.applications[application_name]
    print('Removing relation betweeen {} and {}'.format(app.name, application_name))
    await model.remove_relation(
        '{}:pgsql'.format(app.name),
        '{}:db'.format(application_name))
    await model.block_until(lambda: sql.status == "active" or sql.status == "error")
    await model.block_until(lambda: app.status == "blocked" or app.status == "error")
    assert sql.status != "error"
    assert app.status != "error"


@pytest.mark.xfail
async def test_mysql_relate(model, series, app, request):
    """Test relating MySQL to GitLab, expect failure due to removal of MySQL support."""
    application_name = 'gitlab-mysql-{}'.format(series)
    sql = model.applications[application_name]
    print('Relating {} with {}'.format(app.name, application_name))
    await model.add_relation(
        '{}:db'.format(app.name),
        application_name)
    await model.block_until(lambda: sql.status == "active" or sql.status == "error")
    await model.block_until(lambda: app.status == "active" or app.status == "error")
    assert sql.status != "error"
    assert app.status != "error"
