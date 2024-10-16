from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import GitHubLoginView, GitHubCallbackView, GitHubReposView, RepoStructureView, ChatView, MessageView, DownloadPDFView

urlpatterns = [
    
    path('github-login/', GitHubLoginView.as_view(), name='github_login'),
    path('github-callback/', GitHubCallbackView.as_view(), name='github_callback'),
    path('github-repos/', GitHubReposView.as_view(), name='github_repos'),
    path('repo-structure/<str:repo_name>/', RepoStructureView.as_view(), name='repo_structure'),
    path('chats/', ChatView.as_view(), name='chats'),
    path('chats/<int:chat_id>/messages/', MessageView.as_view(), name='messages'),
    path('download-pdf/', DownloadPDFView.as_view(), name='download_pdf'),
]