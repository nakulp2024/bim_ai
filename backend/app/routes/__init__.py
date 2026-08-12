from . import config_routes, exports, jobs, projects, rates, schedule

ROUTERS = (
    projects.router,
    schedule.router,
    rates.router,
    exports.router,
    jobs.router,
    config_routes.router,
)

__all__ = ["ROUTERS", "projects", "schedule", "rates", "exports", "jobs", "config_routes"]
