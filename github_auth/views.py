from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework.response import Response
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware, make_aware
import requests
from django.views import View
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from huggingface_hub import InferenceClient
from django.conf import settings

import json
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from .models import Chat, Message
from django.utils.decorators import method_decorator
import os
import logging


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
        profile = user.profile
        profile.github_token = access_token
        profile.github_email = user_data.get('email')
        profile.github_avatar_url = user_data.get('avatar_url')
        profile.save()
        
        # Log the user in and start a session
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
            headers={'Authorization': f'token {github_token}'},
            params={'sort': 'updated', 'direction': 'desc'}  # This sorts repos by last updated time
        )
        
        if response.status_code == 200:
            repos = response.json()
            
            # Convert string dates to datetime objects
            for repo in repos:
                updated_at = parse_datetime(repo['updated_at'])
                if not is_aware(updated_at):
                    updated_at = make_aware(updated_at)
                repo['updated_at'] = updated_at
            
            # Sort repos by updated_at (most recent first)
            sorted_repos = sorted(repos, key=lambda x: x['updated_at'], reverse=True)
            
            return Response(sorted_repos)
        else:
            return Response({"error": "Failed to fetch repositories"}, status=response.status_code)
class RepoStructureView(LoginRequiredMixin, View):
    def get(self, request, repo_name):
        github_token = request.user.profile.github_token
        if not github_token:
            return JsonResponse({"error": "GitHub token not found"}, status=400)

        response = requests.get(
            f'https://api.github.com/repos/{request.user.username}/{repo_name}/git/trees/main?recursive=1',
            headers={'Authorization': f'token {github_token}'}
        )
        
        if response.status_code == 200:
            return JsonResponse(response.json())
        else:
            return JsonResponse({"error": "Failed to fetch repository structure"}, status=response.status_code)

@method_decorator(csrf_exempt, name='dispatch')
class ChatView(LoginRequiredMixin, View):
    def get(self, request):
        chats = Chat.objects.filter(user=request.user).values('id', 'chat_name', 'created_at')
        return JsonResponse(list(chats), safe=False)

    def post(self, request):
        data = json.loads(request.body)
        chat_name = data.get('chat_name', f"Chat {Chat.objects.filter(user=request.user).count() + 1}")
        chat = Chat.objects.create(user=request.user, chat_name=chat_name)
        return JsonResponse({
            'id': chat.id,
            'chat_name': chat.chat_name,
            'created_at': chat.created_at
        })

@method_decorator(csrf_exempt, name='dispatch')
class MessageView(LoginRequiredMixin, View):
    def get(self, request, chat_id):
        try:
            chat = Chat.objects.get(id=chat_id, user=request.user)
        except Chat.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        messages = Message.objects.filter(chat=chat).values('sender', 'text', 'timestamp')
        return JsonResponse(list(messages), safe=False)

    def post(self, request, chat_id):
        try:
            chat = Chat.objects.get(id=chat_id, user=request.user)
        except Chat.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        data = json.loads(request.body)
        
        user_message = Message.objects.create(
            chat=chat,
            sender='user',
            text=data.get('text', '')
        )
        print(type(user_message.text), "=============================================")

        # Here you would integrate with Mistral AI
        # For now, we'll just echo the message
        
        
        # Use Hugging Face InferenceClient to get the API response
        client = InferenceClient(api_key="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")

        # Assuming the response is structured as a list of messages
        api_response = client.chat_completion(
            model="mistralai/Mistral-7B-Instruct-v0.3",
            messages=[{"role": "user", "content": user_message.text}],
            max_tokens=500,
        )

        # Assuming the API returns a dictionary with a 'choices' key
        if isinstance(api_response, dict) and 'choices' in api_response:
            bot_message_text = api_response['choices'][0]['message']['content']
        else:
            # Handle unexpected response format
            bot_message_text = str(api_response)

        bot_message = Message.objects.create(
            chat=chat,
            sender='bot',
            text=bot_message_text
        )


        return JsonResponse({
            'user_message': {
                'sender': user_message.sender,
                'text': user_message.text,
                'timestamp': user_message.timestamp
            },
            'bot_response': {
                'sender': bot_message.sender,
                'text': bot_message.text,
                'timestamp': bot_message.timestamp
            }
        })
        
        
        
        
# LLM API View for generating responses and PDF
logger = logging.getLogger(__name__)

class LLMResponseView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.info(f"Received data: {data}")
            question = data.get('question', '')

            # Interact with Mistral model via Hugging Face's InferenceClient
            client = InferenceClient(api_key="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")
            api_response = ""

            for message in client.chat_completion(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                messages=[{"role": "user", "content": question}],
                max_tokens=500,
                stream=True,
            ):
                api_response += message.choices[0].delta.content

            return JsonResponse({'api_response': api_response}, status=200)

        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            return JsonResponse({"error": "Invalid JSON format"}, status=400)

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            return JsonResponse({"error": "Internal Server Error"}, status=500)
@method_decorator(csrf_exempt, name='dispatch')
class DownloadPDFView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body)
        api_response = data.get('api_response', '')

        # Generate PDF
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Title
        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, height - 50, "API Response:")

        # Set normal font for the response text
        p.setFont("Helvetica", 12)
        text_y = height - 80

        def draw_wrapped_text(x, y, text, max_width):
            words = text.split(' ')
            line = ''
            for word in words:
                test_line = f"{line} {word}".strip()
                text_width = p.stringWidth(test_line, "Helvetica", 12)

                if text_width < max_width:
                    line = test_line
                else:
                    p.drawString(x, y, line)
                    y -= 14
                    line = word

            if line:
                p.drawString(x, y, line)

        draw_wrapped_text(100, text_y, api_response, 450)

        # Save the PDF to the buffer
        p.showPage()
        p.save()

        # Return PDF as HTTP response
        buffer.seek(0)
        return HttpResponse(buffer, content_type='application/pdf')