# views.py
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from rest_framework.views import APIView
import requests

class GitHubLoginView(APIView):
    def get(self, request):
        github_login_url = f'https://github.com/login/oauth/authorize?client_id={settings.GITHUB_CLIENT_ID}&redirect_uri={settings.GITHUB_REDIRECT_URI}'
        return JsonResponse({'authorization_url': github_login_url})

class GitHubCallbackView(APIView):
    def get(self, request):
        code = request.GET.get('code')
        access_token = self.get_access_token(code)
        user_data = self.get_user_data(access_token)
        

        
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