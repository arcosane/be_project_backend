from django.urls import path
from .views import GitHubLoginView, GitHubCallbackView, GitHubReposView

urlpatterns = [
    path('github-login/', GitHubLoginView.as_view(), name='github_login'),
    path('github-callback/', GitHubCallbackView.as_view(), name='github_callback'),
    path('github-repos/', GitHubReposView.as_view(), name='github_repos'),
]