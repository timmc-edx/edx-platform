from rest_framework import serializers


class CreateCourseSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=200)
    secret_key = serializers.CharField(max_length=100)
    organization_key = serializers.CharField(max_length=64)
    course_id = serializers.CharField(max_length=200, required=False)
