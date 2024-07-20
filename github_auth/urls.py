from django.urls import path
from .views import GitHubLoginView, GitHubCallbackView

urlpatterns = [
    path('github-login/', GitHubLoginView.as_view(), name='github_login'),
    path('github-callback/', GitHubCallbackView.as_view(), name='github_callback'),
]