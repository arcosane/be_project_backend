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
from collections import Counter
import re
import json
from django.contrib.auth.mixins import LoginRequiredMixin
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from .models import Chat, Message, GenChat, GenMessage, RoadMapMessage, RoadMap
from django.utils.decorators import method_decorator
import os
import logging
from reportlab.platypus import BaseDocTemplate, Paragraph, Spacer, Frame, PageTemplate, SimpleDocTemplate
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import letter

from io import BytesIO


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
        messages = Message.objects.filter(chat=chat).order_by('timestamp').values('sender', 'text')
        conversation_history = [
            {
                "role": "user" if msg['sender'] == 'user' else "bot",
                "content": msg['text']
            }
            for msg in messages
        ]
        user_message = Message.objects.create(
            chat=chat,
            sender='user',
            text=data.get('text', '')
        )
        print(type(user_message.text), "=============================================")

        # For now, we'll just echo the message
        
        enhanced_prompt = f"""
        conversation history: {conversation_history}
        user's current prompt: {user_message.text}
        """
        
        # Use Hugging Face InferenceClient to get the API response
        client = InferenceClient(api_key="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")

        # Assuming the response is structured as a list of messages
        api_response = client.chat_completion(
            model="mistralai/Mistral-7B-Instruct-v0.3",
            messages=[{"role": "user", "content": enhanced_prompt}],
            max_tokens=1000,
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

@method_decorator(csrf_exempt, name='dispatch')
class LLMResponseView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.info(f"Received data: {data}")
            question = data.get('question', '')

            client = InferenceClient(api_key="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")
            api_response = ""

            for message in client.chat_completion(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                messages=[{"role": "user", "content": question}],
                max_tokens=1000,
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
        api_response = api_response.replace("<br>", "<br/>")

        buffer = BytesIO()
        doc = BaseDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        title_style = styles['h1']
        title_style.alignment = 1  # Center alignment
        paragraph_style = styles['Normal']
        paragraph_style.fontSize = 10
        paragraph_style.leading = 12
        paragraph_style.wordWrap = 'CJK'
        paragraph_style.splitLongWords = True

        # Define frames (columns)
        frame_width = doc.width / 2 - 0.5 * inch  # Half the page width minus some margin
        left_frame = Frame(doc.leftMargin, doc.bottomMargin, frame_width, doc.height,
                         id='left_frame')
        right_frame = Frame(doc.leftMargin + doc.width / 2 + 0.5 * inch, doc.bottomMargin, frame_width, doc.height,
                          id='right_frame')

        # Define page template
        page_template = PageTemplate(id='two_column', frames=[left_frame, right_frame], onPage=self.add_header_footer)
        doc.addPageTemplates([page_template])

        # Build story (content)
        story = []
        title = Paragraph("Report:", title_style)
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # Split the content into sections based on headings
        sections = re.split(r"(<h3>.*?</h3>)", api_response)
        sections = [s.strip() for s in sections if s.strip()]

        for section in sections:
            if section.startswith("<h3>"):
                heading_text = section[4:-5]
                heading_style = styles['h2']
                heading = Paragraph(heading_text, heading_style)
                story.append(heading)
                story.append(Spacer(1, 0.1 * inch))
            else:
                content = Paragraph(section, paragraph_style)
                story.append(content)
                story.append(Spacer(1, 0.1 * inch))

        # Build the PDF
        doc.build(story)

        buffer.seek(0)
        return HttpResponse(buffer, content_type='application/pdf')

    def add_header_footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 9)
        canvas.drawString(inch, 0.75 * inch, "Page %d" % doc.page)
        canvas.restoreState()


@method_decorator(csrf_exempt, name='dispatch')
class ExtractFilesFromGithub(LoginRequiredMixin,View):
    def post(self,request):
        data = json.loads(request.body)



#summaries the repo
import base64

@method_decorator(csrf_exempt, name='dispatch')
class GitHubRepoSummarizerView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body)
        repo_name = data.get('repo_name')
        chat_id = data.get('chat_id')  # Add this line to get the chat_id from the request
        
        if not repo_name:
            return JsonResponse({"error": "Repository name is required"}, status=400)

        if not chat_id:
            return JsonResponse({"error": "Chat ID is required"}, status=400)

        github_token = request.user.profile.github_token
        if not github_token:
            return JsonResponse({"error": "GitHub token not found"}, status=400)

        # Fetch repository contents
        repo_contents = self.fetch_repo_contents(request.user.username, repo_name, github_token)
        
        if isinstance(repo_contents, dict) and 'error' in repo_contents:
            return JsonResponse(repo_contents, status=400)

        # Prepare content for LLM
        content_for_llm = self.prepare_content_for_llm(repo_contents)

        # Generate summary using LLM
        summary = self.generate_summary(content_for_llm)

        # Save the summary as a new message
        try:
            chat = Chat.objects.get(id=chat_id, user=request.user)
            message = Message.objects.create(
                chat=chat,
                sender='bot',
                text=f"Summary of repository '{repo_name}':\n\n{summary}"
            )
        except Chat.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": f"Failed to save message: {str(e)}"}, status=500)

        return JsonResponse({
            "summary": summary,
            "message_id": message.id
        })

    def fetch_repo_contents(self, username, repo_name, token, path=''):
        url = f'https://api.github.com/repos/{username}/{repo_name}/contents/{path}'
        headers = {'Authorization': f'token {token}'}
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return {"error": "Failed to fetch repository contents"}

        contents = response.json()
        result = []

        for item in contents:
            if item['type'] == 'file':
                file_content = self.fetch_file_content(item['download_url'], token)
                result.append({
                    'name': item['name'],
                    'path': item['path'],
                    'content': file_content
                })
            elif item['type'] == 'dir':
                result.extend(self.fetch_repo_contents(username, repo_name, token, item['path']))

        return result

    def fetch_file_content(self, url, token):
        headers = {'Authorization': f'token {token}'}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            try:
                # GitHub API returns the content directly, not base64 encoded
                return response.text
            except Exception as e:
                print(f"Error decoding content: {str(e)}")
                return "[Content could not be decoded]"
        return ""

    def prepare_content_for_llm(self, repo_contents):
        content = "Repository structure and file contents:\n\n"
        for item in repo_contents:
            content += f"File: {item['path']}\n"
            content += f"Content:\n{item['content'][:1000]}...\n\n"  # Limit content to 1000 characters per file
        return content

    def generate_summary(self, content):
        
        prompt = f"""
        Use proper formatting and break down the information into sections with clear headings for easy readability.

You are an expert project report generator specializing in AI/ML and Data Science projects. Based on the topic provided by the user, generate a detailed project report. Ensure that if multiple models or approaches are used, you provide a comprehensive comparison of their performance and characteristics.

Ensure to include the following:

1. Title: A concise and informative title that accurately reflects the project's focus.

2. Abstract: A brief summary of the entire project (around 200-300 words). It should cover the problem being addressed, the data used, the models or approaches implemented, key results (including performance metrics), and main conclusions (including model comparisons).

3. Keywords: A list of 4-6 relevant keywords that can help with indexing and searching for the paper. Include keywords related to the specific algorithms, models, and data used.

4. Introduction:
   * Background: Provide context for the project, explaining the problem being addressed and its significance in the AI/ML or Data Science domain.
   * Motivation: Explain why this project is important or necessary. What gap does it fill, or what problem does it solve in the context of AI/ML or Data Science?
   * Objectives: Clearly state the goals and objectives of the project. What specific AI/ML or Data Science tasks did you aim to achieve (e.g., classification, regression, clustering, etc.)?
   * Scope: Define the boundaries of the project. What datasets, models, and techniques were included? What was explicitly excluded?

5. Literature Review: (Critically) review existing research and publications relevant to the project, focusing on related AI/ML or Data Science approaches. This section should:
   * Identify Key Related Works: Identify relevant research papers, surveys, and blog posts that discuss similar AI/ML or Data Science problems and solutions.
   * Summarize the Findings of Those Works: Provide concise summaries of the approaches used in each related work, highlighting their strengths and weaknesses.
   * Compare and Contrast Different Approaches: Compare and contrast different AI/ML or Data Science techniques used in the literature, focusing on their suitability for the problem at hand.
   * Highlight the Limitations of Existing Work: Identify any limitations or drawbacks of existing AI/ML or Data Science solutions.
   * Explain How Your Project Builds Upon or Differs from Previous Research: Clearly articulate how your project extends or improves upon existing AI/ML or Data Science approaches.

6. Methodology: Describe in detail the AI/ML or Data Science approach used to conduct the project. This section should be reproducible.
   * Data Description: Describe the dataset(s) used, including their size, features, and source. Explain any data cleaning or preprocessing steps performed.
   * Model Selection: Justify the choice of models or approaches. If multiple models were used, explain the rationale behind each selection and how they relate to the problem.
   * Feature Engineering: Describe any feature engineering steps performed, including the creation of new features and the selection of relevant features.
   * Training and Evaluation: Explain the training process for each model, including hyperparameter tuning, cross-validation, and performance metrics.
   * Different Approaches Used: Explain each approach used in detail; what different algorithms were used, and why were they selected.

7. Results: Present the findings of the project in a clear and objective manner, focusing on the performance of different models or approaches.
   * Quantitative Results: Present numerical data using tables, graphs, and charts. Include key performance metrics (e.g., accuracy, precision, recall, F1-score, AUC-ROC, RMSE, R-squared) for each model.
   * Compare the Performance or the Results of These Models: Compare the performance of different models or approaches based on the chosen performance metrics. Highlight any statistically significant differences in performance.
   * Qualitative Results: Describe any qualitative observations or insights gained from the project.
   * Figures/Screenshots: Include relevant figures, screenshots, or diagrams to illustrate the results. Provide captions for all figures.

8. Discussion: Interpret the results and discuss their implications, focusing on the strengths and weaknesses of different models or approaches.
   * Interpretation of Results: Explain the meaning of the results in the context of the problem being addressed. Discuss the factors that contributed to the performance of each model.
   * Comparison with Existing Work: Compare the performance of your models with the results reported in the literature. Discuss any similarities or differences in performance.
   * Limitations: Acknowledge the limitations of your project, including potential sources of bias or error in the data or methodology.

9. Conclusion: Summarize the key findings and contributions of the project, highlighting the relative performance of different models or approaches.
   * Summary of Findings: Briefly restate the main results, including a summary of the performance of each model.
   * Contributions: Clearly state the contributions of the project to the AI/ML or Data Science domain. What new insights did you gain about the problem or the models?
   * Future Work: Suggest potential directions for future research or development, building upon the findings of your project. Consider improvements to the models, new datasets to explore, or alternative approaches to investigate.

10. References: List all the research papers, books, websites, and other sources that were cited in the report. Use a consistent citation style (e.g., APA, MLA, Chicago).

11. Appendix (Optional): Include any supplementary materials that are not essential to the main body of the report, such as detailed code listings, raw data, or additional figures.

Formatting Guidelines:

* Use clear and concise language.
* Use proper grammar and spelling.
* Follow a consistent formatting style throughout the report.
* Use headings and subheadings to organize the content.
* Make sure the headings like Title, Abstract, etc. are bold and larger font
* Provide captions for all figures and tables.
* Cite all sources properly.
* Use bullet points or numbered lists to present information in a clear and organized manner.
* Maintain an objective and unbiased tone.
* Be detailed and clear, provide a section about how to access and use the project, along with its features. If possible, provide instructions or links to a simple installation/execution

Repository content:
{content}"""
        
        print("===================================\n",content)
        
        client = InferenceClient(api_key="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")
        #prompt = f"Please provide a concise summary of the following GitHub repository contents:\n\n{content}\n\nSummary:"

        api_response = client.chat_completion(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000
                )
        response = api_response['choices'][0]['message']['content'] if 'choices' in api_response else str(api_response)
        formatted_report = self.format_report(response)
        return formatted_report
    
    def format_report(self, report_text):
        # 1. Split into sections based on bold headings
        sections = re.split(r"(\*\*.*?\*\*)", report_text)
        sections = [s.strip() for s in sections if s.strip()]

        formatted_report = ""

        for i, section in enumerate(sections):
            # 2. Identify and format headings
            if section.startswith("**") and section.endswith("**"):
                heading = section[2:-2].strip()
                formatted_report += f"<h3>{heading}</h3>\n"
            else:
                # 3. Format the content
                content = self.format_content(section)
                formatted_report += f"<p>{content}</p>\n"

        return formatted_report


    def format_content(self, content):

        # Handle ordered lists
        content = re.sub(r"\n(\d+\.\s)", r"\n<ol><li>\1", content)
        content = re.sub(r"(\d+\.)(.*?)(?=\n|$)", r"<li>\1\2</li>", content)
        content = re.sub(r"</li>\n</ol>", r"</li></ol>", content)


        # Handle unordered lists
        content = re.sub(r"\n\* ", r"\n<ul><li>", content)
        content = re.sub(r"\* (.*?)(?=\n|$)", r"<li>\1</li>", content)
        content = re.sub(r"</li>\n</ul>", r"</li></ul>", content)

        # Add line breaks between paragraphs
        content = re.sub(r"\n\n", r"\n<br>\n", content)

        #Handle edge cases:
        if content.startswith("<li>"):
            content = "<ul>" + content + "</ul>"

        return content


    
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

@method_decorator(csrf_exempt, name='dispatch')
class GitHubCodeAnalysisView(LoginRequiredMixin, APIView):
    def post(self, request):
        data = request.data  # Use request.data instead of reading request.body
        repo_name = data.get('repo_name')
        
        if not repo_name:
            return Response({"error": "Repository name is required"}, status=400)

        github_token = request.user.profile.github_token
        if not github_token:
            return Response({"error": "GitHub token not found"}, status=400)

        # Fetch repository contents
        repo_contents = self.fetch_repo_contents(request.user.username, repo_name, github_token)
        
        if isinstance(repo_contents, dict) and 'error' in repo_contents:
            return Response(repo_contents, status=400)

        # Analyze code
        analysis_result = self.analyze_code(repo_contents)

        return Response(analysis_result)

    def fetch_repo_contents(self, username, repo_name, token, path=''):
        url = f'https://api.github.com/repos/{username}/{repo_name}/contents/{path}'
        headers = {'Authorization': f'token {token}'}
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return {"error": "Failed to fetch repository contents"}

        contents = response.json()
        result = []

        for item in contents:
            if item['type'] == 'file':
                file_content = self.fetch_file_content(item['download_url'], token)
                result.append({
                    'name': item['name'],
                    'path': item['path'],
                    'content': file_content
                })
            elif item['type'] == 'dir':
                result.extend(self.fetch_repo_contents(username, repo_name, token, item['path']))

        return result

    def fetch_file_content(self, url, token):
        headers = {'Authorization': f'token {token}'}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text
        return ""

    def analyze_code(self, repo_contents):
        language_stats = self.get_language_stats(repo_contents)
        file_summaries = self.get_file_summaries(repo_contents)
        improvement_suggestions = self.get_improvement_suggestions(repo_contents)

        return {
            'language_stats': language_stats,
            'file_summaries': file_summaries,
            'improvement_suggestions': improvement_suggestions
        }

    def get_language_stats(self, repo_contents):
        language_extensions = {
            'py': 'Python',
            'js': 'JavaScript',
            'html': 'HTML',
            'css': 'CSS',
            'json': 'JSON',
            'md': 'Markdown'
        }
        
        language_counts = Counter()
        
        for file in repo_contents:
            ext = file['name'].split('.')[-1].lower()
            language = language_extensions.get(ext, 'Other')
            language_counts[language] += len(file['content'])
        
        total_bytes = sum(language_counts.values())
        language_percentages = {lang: count / total_bytes * 100 for lang, count in language_counts.items()}
        
        return language_percentages

    def get_file_summaries(self, repo_contents):
        client = InferenceClient(api_key="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")
        summaries = {}

        for file in repo_contents:
            prompt = f"You are a highly skilled software engineer. Analyze the following file in detail and provide a deep, line-by-line technical explanation. For each line or block, explain what it does, why it's written that way, and how it fits into the overall purpose of the file. Also mention any design patterns, potential improvements, or performance concerns. File name: {file['name']} Content: {file['content']}"
            response = client.text_generation(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                prompt=prompt,
                max_new_tokens=1000
            )
            summaries[file['path']] = response

        return summaries

    def get_improvement_suggestions(self, repo_contents):
        client = InferenceClient(api_key="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")
        suggestions = {}

        for file in repo_contents:
            prompt = f"Analyze this {file['name']} file and suggest improvements and optimizations in short :\n\n{file['content'][:1000]}..."
            response = client.text_generation(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                prompt=prompt,
                max_new_tokens=300
            )
            suggestions[file['path']] = response

        return suggestions
import PyPDF2
@method_decorator(csrf_exempt, name='dispatch')
class CodeGenMessageView(LoginRequiredMixin, View):
    def get(self, request, chat_id):
        try:
            chat = GenChat.objects.get(id=chat_id, user=request.user)
        except GenChat.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        messages = GenMessage.objects.filter(chat=chat).values('sender', 'text', 'timestamp')
        return JsonResponse(list(messages), safe=False)

    def post(self, request, chat_id):
        try:
            chat = GenChat.objects.get(id=chat_id, user=request.user)
        except GenChat.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        text_input = request.POST.get('text', '')
        pdf_file = request.FILES.get('pdf')
        pdf_text = ""
        if pdf_file:
            try:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                for page in range(len(pdf_reader.pages)):
                    pdf_text += pdf_reader.pages[page].extract_text()
            except PyPDF2.errors.PdfReadError:
                return JsonResponse({"error": "Error reading PDF file"}, status=400)
            except Exception as e:
                return JsonResponse({"error": f"Unexpected error processing PDF: {e}"}, status=500)

        # Save the user's message
        user_text = text_input + "\n" + pdf_text
        user_message = GenMessage.objects.create(
            chat=chat,
            sender='user',
            text=user_text
        )

        # Retrieve recent conversation history
        messages = GenMessage.objects.filter(chat=chat).order_by('timestamp').values('sender', 'text')
        conversation_history = [
            {
                "role": "user" if msg['sender'] == 'user' else "bot",
                "content": msg['text']
            }
            for msg in messages
        ]

        # Enhanced prompt including memory
        enhanced_prompt = f"""
You are a highly skilled software engineer specializing in algorithm design and code optimization.
Your task is to analyze a given project report and generate code that outlines the core logic and functionality of the described system.
The code should be clear, concise, and easily understandable by another software engineer. Focus on representing the essential steps and decision points, omitting language-specific syntax.

Project Report:
{user_text}

Conversation history: {conversation_history}

Generate code that implements this project.
"""

        # Use Hugging Face InferenceClient to get the API response
        client = InferenceClient(api_key="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")

        try:
            # Get the model response
            api_response = client.chat_completion(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                messages=[{"role": "user", "content": enhanced_prompt}],
                max_tokens=1000,
            )
            bot_message_text = api_response['choices'][0]['message']['content'] if 'choices' in api_response else str(api_response)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        # Wrap bot message code in <pre><code> tags to preserve formatting
        bot_message_text = f"<pre><code>{bot_message_text}</code></pre>"

        # Save bot's response
        bot_message = GenMessage.objects.create(
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
      
@method_decorator(csrf_exempt, name='dispatch')
class GenChatView(LoginRequiredMixin, View):
    def get(self, request):
        chats = GenChat.objects.filter(user=request.user).values('id', 'chat_name', 'created_at')
        return JsonResponse(list(chats), safe=False)

    def post(self, request):
        data = json.loads(request.body)
        chat_name = data.get('chat_name', f"Chat {GenChat.objects.filter(user=request.user).count() + 1}")
        chat = GenChat.objects.create(user=request.user, chat_name=chat_name)
        return JsonResponse({
            'id': chat.id,
            'chat_name': chat.chat_name,
            'created_at': chat.created_at
        })
        
@method_decorator(csrf_exempt, name='dispatch')
class RoadMapMessageView(LoginRequiredMixin, View):
    def get(self, request, chat_id):
        try:
            chat = RoadMap.objects.get(id=chat_id, user=request.user)
        except RoadMap.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        messages = RoadMapMessage.objects.filter(chat=chat).values('sender', 'text', 'timestamp')
        return JsonResponse(list(messages), safe=False)

    def post(self, request, chat_id):
        try:
            chat = RoadMap.objects.get(id=chat_id, user=request.user)
        except RoadMap.DoesNotExist:
            return JsonResponse({"error": "Chat not found"}, status=404)

        data = json.loads(request.body)

        # Save the user's message
        user_message = RoadMapMessage.objects.create(
            chat=chat,
            sender='user',
            text=data.get('text', '')
        )
        user_text = data.get('text', '')

        # Retrieve recent conversation history
        messages = RoadMapMessage.objects.filter(chat=chat).order_by('timestamp').values('sender', 'text')
        conversation_history = [
            {
                "role": "user" if msg['sender'] == 'user' else "bot",
                "content": msg['text']
            }
            for msg in messages
        ]

        # Enhanced prompt including memory
        enhanced_prompt = f"""
        You are an expert project roadmap generator. Based on the topic provided by the user, generate a detailed project roadmap. 
        Ensure to include the following:

        1. A list of **tasks to be done** to complete the project.
        2. An **estimated timeline** for each task or the overall project.
        3. A detailed **sequence and plan of action** to achieve the project goals.
        4. A list of **references** as in research papers related to the project and additional support for the project.
        5. A suggested **tech stack** suitable for this project.
        6. The **features** to build for a successful project delivery.
        7. Any other **helpful references or support** the user might need.

        Use proper formatting and break down the information into sections with clear headings for easy readability. Keep the responses concise yet informative.

        Conversation history : {conversation_history}

        User's topic:
        {user_text}
        """

        # Use Hugging Face InferenceClient to get the API response
        client = InferenceClient(api_key="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")

        try:
            # Get the model response
            api_response = client.chat_completion(
                model="mistralai/Mistral-7B-Instruct-v0.3",
                messages=[{"role": "user", "content": enhanced_prompt}],
                max_tokens=1000,
            )
            bot_message_text = api_response['choices'][0]['message']['content'] if 'choices' in api_response else str(api_response)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

        # Wrap bot message code in <pre><code> tags to preserve formatting
        bot_message_text = f"<pre><code>{bot_message_text}</code></pre>"

        # Save bot's response
        bot_message = RoadMapMessage.objects.create(
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


@method_decorator(csrf_exempt, name='dispatch')
class RoadMapChatVIew(LoginRequiredMixin, View):
    def get(self, request):
        chats = RoadMap.objects.filter(user=request.user).values('id', 'chat_name', 'created_at')
        return JsonResponse(list(chats), safe=False)

    def post(self, request):
        data = json.loads(request.body)
        chat_name = data.get('chat_name', f"Chat {RoadMap.objects.filter(user=request.user).count() + 1}")
        chat = RoadMap.objects.create(user=request.user, chat_name=chat_name)
        return JsonResponse({
            'id': chat.id,
            'chat_name': chat.chat_name,
            'created_at': chat.created_at
        })
        
@method_decorator(csrf_exempt, name='dispatch')      
def fused_repo_summary(request):
    repo_name = request.data.get('repo_name')
    if not repo_name:
        return Response({"error": "Repository name is required"}, status=400)

    # Fetch repository contents (reuse your existing logic)
    github_token = request.user.profile.github_token
    repo_contents = GitHubRepoSummarizerView().fetch_repo_contents(request.user.username, repo_name, github_token) # reusing your code for fetching repo content
    if isinstance(repo_contents, dict) and 'error' in repo_contents:
        return Response(repo_contents, status=400)

    content = GitHubRepoSummarizerView().prepare_content_for_llm(repo_contents)

    # LLM 1: The Professor
    client = InferenceClient(api_key="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")
    prompt_professor = f"""
        You are a highly experienced computer science professor with expertise in software engineering.
        Your task is to analyze the following GitHub repository and explain its purpose, functionality,
        and key components in a way that is easy for another AI model to understand.
        Focus on providing clear and concise information that will help the other AI model generate a detailed and elaborate summary.

        Repository Content:
        {content}

        Explanation:
        """

    professor_explanation = client.chat_completion(
        model="mistralai/Mistral-7B-Instruct-v0.3", # Replace with your model choice
        messages=[{"role": "user", "content": prompt_professor}],
        max_tokens=1000
    )['choices'][0]['message']['content']


    # LLM 2: The Elaborator
    prompt_elaborator = f"""
        Use proper formatting and break down the information into sections with clear headings for easy readability.

You are an expert project report generator specializing in AI/ML and Data Science projects. Based on the topic provided by the user, generate a detailed project report. Ensure that if multiple models or approaches are used, you provide a comprehensive comparison of their performance and characteristics.

Ensure to include the following:

1. Title: A concise and informative title that accurately reflects the project's focus.

2. Abstract: A brief summary of the entire project (around 200-300 words). It should cover the problem being addressed, the data used, the models or approaches implemented, key results (including performance metrics), and main conclusions (including model comparisons).

3. Keywords: A list of 4-6 relevant keywords that can help with indexing and searching for the paper. Include keywords related to the specific algorithms, models, and data used.

4. Introduction:
   * Background: Provide context for the project, explaining the problem being addressed and its significance in the AI/ML or Data Science domain.
   * Motivation: Explain why this project is important or necessary. What gap does it fill, or what problem does it solve in the context of AI/ML or Data Science?
   * Objectives: Clearly state the goals and objectives of the project. What specific AI/ML or Data Science tasks did you aim to achieve (e.g., classification, regression, clustering, etc.)?
   * Scope: Define the boundaries of the project. What datasets, models, and techniques were included? What was explicitly excluded?

5. Literature Review: (Critically) review existing research and publications relevant to the project, focusing on related AI/ML or Data Science approaches. This section should:
   * Identify Key Related Works: Identify relevant research papers, surveys, and blog posts that discuss similar AI/ML or Data Science problems and solutions.
   * Summarize the Findings of Those Works: Provide concise summaries of the approaches used in each related work, highlighting their strengths and weaknesses.
   * Compare and Contrast Different Approaches: Compare and contrast different AI/ML or Data Science techniques used in the literature, focusing on their suitability for the problem at hand.
   * Highlight the Limitations of Existing Work: Identify any limitations or drawbacks of existing AI/ML or Data Science solutions.
   * Explain How Your Project Builds Upon or Differs from Previous Research: Clearly articulate how your project extends or improves upon existing AI/ML or Data Science approaches.

6. Methodology: Describe in detail the AI/ML or Data Science approach used to conduct the project. This section should be reproducible.
   * Data Description: Describe the dataset(s) used, including their size, features, and source. Explain any data cleaning or preprocessing steps performed.
   * Model Selection: Justify the choice of models or approaches. If multiple models were used, explain the rationale behind each selection and how they relate to the problem.
   * Feature Engineering: Describe any feature engineering steps performed, including the creation of new features and the selection of relevant features.
   * Training and Evaluation: Explain the training process for each model, including hyperparameter tuning, cross-validation, and performance metrics.
   * Different Approaches Used: Explain each approach used in detail; what different algorithms were used, and why were they selected.

7. Results: Present the findings of the project in a clear and objective manner, focusing on the performance of different models or approaches.
   * Quantitative Results: Present numerical data using tables, graphs, and charts. Include key performance metrics (e.g., accuracy, precision, recall, F1-score, AUC-ROC, RMSE, R-squared) for each model.
   * Compare the Performance or the Results of These Models: Compare the performance of different models or approaches based on the chosen performance metrics. Highlight any statistically significant differences in performance.
   * Qualitative Results: Describe any qualitative observations or insights gained from the project.
   * Figures/Screenshots: Include relevant figures, screenshots, or diagrams to illustrate the results. Provide captions for all figures.

8. Discussion: Interpret the results and discuss their implications, focusing on the strengths and weaknesses of different models or approaches.
   * Interpretation of Results: Explain the meaning of the results in the context of the problem being addressed. Discuss the factors that contributed to the performance of each model.
   * Comparison with Existing Work: Compare the performance of your models with the results reported in the literature. Discuss any similarities or differences in performance.
   * Limitations: Acknowledge the limitations of your project, including potential sources of bias or error in the data or methodology.

9. Conclusion: Summarize the key findings and contributions of the project, highlighting the relative performance of different models or approaches.
   * Summary of Findings: Briefly restate the main results, including a summary of the performance of each model.
   * Contributions: Clearly state the contributions of the project to the AI/ML or Data Science domain. What new insights did you gain about the problem or the models?
   * Future Work: Suggest potential directions for future research or development, building upon the findings of your project. Consider improvements to the models, new datasets to explore, or alternative approaches to investigate.

10. References: List all the research papers, books, websites, and other sources that were cited in the report. Use a consistent citation style (e.g., APA, MLA, Chicago).

11. Appendix (Optional): Include any supplementary materials that are not essential to the main body of the report, such as detailed code listings, raw data, or additional figures.

Formatting Guidelines:

* Use clear and concise language.
* Use proper grammar and spelling.
* Follow a consistent formatting style throughout the report.
* Use headings and subheadings to organize the content.
* Provide captions for all figures and tables.
* Cite all sources properly.
* Use bullet points or numbered lists to present information in a clear and organized manner.
* Maintain an objective and unbiased tone.
* Be detailed and clear, provide a section about how to access and use the project, along with its features. If possible, provide instructions or links to a simple installation/execution

Repository content:
{professor_explanation}"""
        
    elaborated_summary = client.chat_completion(
        model="mistralai/Mistral-7B-Instruct-v0.3", # Replace with your model choice
        messages=[{"role": "user", "content": prompt_elaborator}],
        max_tokens=1000
    )['choices'][0]['message']['content']

    return Response({"summary": elaborated_summary})

