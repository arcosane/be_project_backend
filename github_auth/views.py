from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import login
from django.contrib.auth.models import User
import requests

class GitHubLoginView(APIView):
    def get(self, request):
        github_login_url = f'https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}&redirect_uri={settings.GITHUB_REDIRECT_URI}&scope=repo'
        return JsonResponse({'authorization_url': github_login_url})

class GitHubCallbackView(APIView):
    def get(self, request):
        code = request.GET.get('code')
        access_token = self.get_access_token(code)
        user_data = self.get_user_data(access_token)
        
        # Create or get the user
        user, _ = User.objects.get_or_create(username=user_data['login'])
        user.profile.github_token = access_token
        user.profile.save()
        
        # Log the user in
        login(request, user)
        
        return redirect(f'{settings.FRONTEND_URL}/home?username={user_data["login"]}')

    def get_access_token(self, code):
        response = requests.post(
            'https://github.com/login/oauth/access_token',
            data={
                'client_id': settings.GITHUB_CLIENT_ID,
                'client_secret': settings.GITHUB_CLIENT_SECRET,
                'code': code,
            },
            headers={'Accept': 'application/json'}
        )
        return response.json()['access_token']

    def get_user_data(self, access_token):
        response = requests.get(
            'https://api.github.com/user',
            headers={'Authorization': f'token {access_token}'}
        )
        return response.json()

class GitHubReposView(APIView):
    def get(self, request):
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "User not authenticated"}, status=401)
        
        github_token = user.profile.github_token
        if not github_token:
            return Response({"error": "GitHub token not found"}, status=400)

        response = requests.get(
            'https://api.github.com/user/repos',
            headers={'Authorization': f'token {github_token}'}
        )
        
        if response.status_code == 200:
            repos = response.json()
            return Response(repos)
        else:
            return Response({"error": "Failed to fetch repositories"}, status=response.status_code)