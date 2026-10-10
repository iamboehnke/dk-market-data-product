"""Azure Functions (Python v2-programmeringsmodel, Flex Consumption).

- daily_run: timer, hverdage kl. 07:30 UTC (Statistikbanken opdateres om morgenen)
- run_now:   HTTP POST med funktionsnøgle, til at starte en kørsel manuelt
"""
import json
import logging

import azure.functions as func

from dataproduct.config import Settings
from dataproduct.run import _run_summary, run_pipeline

app = func.FunctionApp()


@app.timer_trigger(schedule="0 30 7 * * 1-5", arg_name="timer", run_on_startup=False, use_monitor=True)
def daily_run(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("Timeren var forsinket, kører alligevel")
    run = run_pipeline(Settings.from_env())
    logging.info("Kørsel færdig: %s", json.dumps(_run_summary(run), ensure_ascii=False))
    if run["status"] == "failed":
        # Får kørslen til at stå som fejlet i Application Insights / Monitor
        raise RuntimeError(f"Kørsel {run['run_id']} fejlede")


@app.route(route="run", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def run_now(req: func.HttpRequest) -> func.HttpResponse:
    skip_sql = req.params.get("skip_sql") == "1"
    run = run_pipeline(Settings.from_env(), skip_sql=skip_sql)
    status = 200 if run["status"] in ("succeeded", "partial") else 500
    return func.HttpResponse(
        json.dumps(_run_summary(run), ensure_ascii=False, indent=2),
        status_code=status,
        mimetype="application/json",
    )
