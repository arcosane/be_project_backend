from django.contrib import admin
from .models import Profile, Chat, Message, GenChat, GenMessage, RoadMap, RoadMapMessage

# Register the Profile model
admin.site.register(Profile)

# Register the Chat model
class ChatAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_name', 'created_at', 'updated_at')
    search_fields = ('chat_name', 'user__username')  # You can search by username as well
    list_filter = ('created_at', 'updated_at')

admin.site.register(Chat, ChatAdmin)

# Register the Message model
class MessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'text', 'timestamp')
    search_fields = ('sender', 'text')
    list_filter = ('timestamp',)

admin.site.register(Message, MessageAdmin)

# Register the GenChat model
class GenChatAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_name', 'created_at', 'updated_at')
    search_fields = ('chat_name', 'user__username')
    list_filter = ('created_at', 'updated_at')

admin.site.register(GenChat, GenChatAdmin)

# Register the GenMessage model
class GenMessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'text', 'timestamp')
    search_fields = ('sender', 'text')
    list_filter = ('timestamp',)

admin.site.register(GenMessage, GenMessageAdmin)

class RoadMapAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_name', 'created_at', 'updated_at')
    search_fields = ('chat_name', 'user__username')
    list_filter = ('created_at', 'updated_at')

admin.site.register(RoadMap, RoadMapAdmin)

class RoadMapMessageAdmin(admin.ModelAdmin):
    list_display = ('chat', 'sender', 'text', 'timestamp')
    search_fields = ('sender', 'text')
    list_filter = ('timestamp',)

admin.site.register(RoadMapMessage, RoadMapMessageAdmin)