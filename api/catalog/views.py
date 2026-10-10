from __future__ import annotations

from datetime import date, datetime, timezone

from django.http import Http404, JsonResponse
from django.shortcuts import render

from . import data

JSON_OPTS = {"json_dumps_params": {"ensure_ascii": False}}


def _unavailable(exc: Exception, api: bool, request=None):
    if api:
        return JsonResponse({"error": "data_unavailable", "detail": str(exc)}, status=503, **JSON_OPTS)
    return render(request, "catalog/unavailable.html", {"detail": str(exc)}, status=503)


def _check_product(product_id: str) -> None:
    if product_id not in data.PRODUCT_IDS:
        raise Http404("Ukendt dataprodukt")


def _parse_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} skal være en dato som 2026-10-08") from exc


# HTML: datakatalog


def index(request):
    try:
        manifest, latest = data.manifest(), data.latest()
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=False, request=request)
    products = [manifest["products"][pid] for pid in data.PRODUCT_IDS if pid in manifest["products"]]
    for p in products:
        p["passed"] = sum(1 for c in p["checks"] if c["passed"])
    runs = manifest.get("runs", [])[:10]
    for r in runs:
        merges = [prod.get("merge", {}) for prod in r["products"].values()]
        for key in ("inserted", "revised", "filled"):
            r[key] = sum(m.get(key, 0) for m in merges)
    return render(request, "catalog/index.html", {
        "manifest": manifest, "latest": latest, "products": products, "runs": runs,
        "updated": datetime.fromisoformat(manifest["updated_at"]),
    })


def product(request, product_id: str):
    _check_product(product_id)
    try:
        manifest = data.manifest()
        contract = data.contract(product_id)
        sample = data.rows(product_id, limit=12)
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=False, request=request)
    info = manifest["products"][product_id]
    base = request.build_absolute_uri("/api/v1/")
    return render(request, "catalog/product.html", {
        "p": info, "contract": contract, "sample": sample,
        "sample_cols": list(sample[0].keys()) if sample else [],
        "api_base": base,
        "first_code": contract["source"]["filters"].get("VALUTA", contract["source"]["filters"].get("INSTRUMENT"))[0],
    })


def health(request):
    try:
        manifest = data.manifest()
    except data.DataUnavailable as exc:
        return JsonResponse({"status": "degraded", "detail": str(exc)}, status=503)
    updated = datetime.fromisoformat(manifest["updated_at"])
    age_hours = round((datetime.now(timezone.utc) - updated).total_seconds() / 3600, 1)
    return JsonResponse({"status": "ok", "data_updated_at": manifest["updated_at"], "age_hours": age_hours})


# JSON-API


def api_index(request):
    base = request.build_absolute_uri("/api/v1/")
    return JsonResponse({
        "name": "Kroner og renter – dataprodukt-API",
        "endpoints": {
            "latest": f"{base}latest/",
            "products": f"{base}products/",
            "contract": f"{base}products/{{product_id}}/",
            "data": f"{base}products/{{product_id}}/data/?from=2026-09-01&to=2026-10-08&code=EUR,USD&limit=100",
            "runs": f"{base}runs/",
        },
        "products": list(data.PRODUCT_IDS),
    }, **JSON_OPTS)


def api_latest(request):
    try:
        return JsonResponse(data.latest(), **JSON_OPTS)
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=True)


def api_runs(request):
    try:
        return JsonResponse({"runs": data.manifest().get("runs", [])}, **JSON_OPTS)
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=True)


def api_products(request):
    try:
        manifest = data.manifest()
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=True)
    items = []
    for pid in data.PRODUCT_IDS:
        p = manifest["products"].get(pid)
        if p:
            items.append({k: p[k] for k in ("id", "name", "version", "domain", "owner", "status",
                                            "latest_date", "rows", "source")})
    return JsonResponse({"products": items}, **JSON_OPTS)


def api_contract(request, product_id: str):
    _check_product(product_id)
    try:
        return JsonResponse(data.contract(product_id), **JSON_OPTS)
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=True)


def api_data(request, product_id: str):
    _check_product(product_id)
    try:
        start = _parse_date(request.GET.get("from"), "from")
        end = _parse_date(request.GET.get("to"), "to")
        limit = int(request.GET.get("limit", "500"))
        if not 1 <= limit <= 5000:
            raise ValueError("limit skal være mellem 1 og 5000")
    except ValueError as exc:
        return JsonResponse({"error": "bad_request", "detail": str(exc)}, status=400, **JSON_OPTS)
    codes = [c.strip().upper() for c in request.GET.get("code", "").split(",") if c.strip()] or None
    try:
        rows = data.rows(product_id, start, end, codes, limit)
    except data.DataUnavailable as exc:
        return _unavailable(exc, api=True)
    return JsonResponse({"product": product_id, "count": len(rows), "rows": rows}, **JSON_OPTS)
