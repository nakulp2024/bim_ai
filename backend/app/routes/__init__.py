from . import config_routes, exports, geometry, jobs, progress, projects, rates, schedule

ROUTERS = (
    projects.router,
    schedule.router,
    rates.router,
    progress.router,
    geometry.router,
    exports.router,
    jobs.router,
    config_routes.router,
)

__all__ = [
    "ROUTERS",
    "config_routes",
    "exports",
    "geometry",
    "jobs",
    "progress",
    "projects",
    "rates",
    "schedule",
]
