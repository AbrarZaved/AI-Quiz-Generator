from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


# --- Extend UserSerializer.Meta.fields to expose the new data ---
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "role", "is_active", "date_joined",
            "contact_number", "current_school",
            "parent_full_name", "parent_email", "parent_contact_number",
            "student_class", "preferred_time", "profile_picture",
        ]
        read_only_fields = fields


class UpdateProfileSerializer(serializers.ModelSerializer):
    """PATCH /auth/me/ — update mutable profile fields.

    Email and role are intentionally excluded; they cannot be changed here.
    All fields are optional so the client can send only the fields it wants
    to update.
    """

    class Meta:
        model = User
        fields = [
            "full_name",
            "contact_number",
            "current_school",
            "parent_full_name",
            "parent_email",
            "parent_contact_number",
            "student_class",
            "preferred_time",
            "profile_picture",
        ]
        # Every field is optional for partial updates.
        extra_kwargs = {field: {"required": False} for field in fields}

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(update_fields=list(validated_data.keys()))
        return instance


class StudentRegistrationSerializer(serializers.ModelSerializer):
    """Stores the 4-step registration flow (no password; account starts inactive)."""

    class Meta:
        model = User
        fields = [
            "id",
            # Step 1 - Student info
            "full_name",
            "email",
            "contact_number",
            "current_school",
            # Step 2 - Parent info
            "parent_full_name",
            "parent_email",
            "parent_contact_number",
            # Step 3 - Class selection
            "student_class",
            # Step 4 - Preferred time
            "preferred_time",
        ]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return value.lower()

    def create(self, validated_data):
        # Create an INACTIVE student; no password from this flow, so mark it unusable.
        user = User.objects.create_user(
            role=User.Role.STUDENT,
            is_active=False,
            password=None,
            **validated_data,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return user



class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, validators=[validate_password], style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "password"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        # Public signup creates an INACTIVE student until the email OTP is verified.
        return User.objects.create_user(
            role=User.Role.STUDENT, is_active=False, **validated_data
        )


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with email + password; returns tokens plus the user object.

    Inactive (unverified) accounts cannot authenticate, so login is blocked
    until the email OTP has been verified.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["full_name"] = user.full_name
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class VerifyAccountSerializer(serializers.Serializer):
    """Verify the signup OTP to activate the account."""

    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    new_password = serializers.CharField(
        validators=[validate_password], style={"input_type": "password"}
    )
