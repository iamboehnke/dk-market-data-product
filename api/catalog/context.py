from django.conf import settings


def site(request):
    return {"repo": settings.GITHUB_REPO_URL}
