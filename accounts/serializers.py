from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.db.models import (
    Avg,
    Case,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    Q,
    Value,
    When,
)

from attempts.models import Attempt
from subscriptions.models import Payment, Subscription

User = get_user_model()


# --- Extend UserSerializer.Meta.fields to expose the new data ---
class UserSerializer(serializers.ModelSerializer):
    plan = serializers.SerializerMethodField()
    is_premium = serializers.SerializerMethodField()
    is_free = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "role", "is_active", "date_joined",
            "contact_number", "current_school",
            "parent_full_name", "parent_email", "parent_contact_number",
            "student_class", "preferred_time", "profile_picture",
            "plan", "is_premium", "is_free",
        ]
        read_only_fields = fields

    def get_plan(self, obj):
        sub = getattr(obj, "subscription", None)
        return sub.plan if sub else "free_trial"

    def get_is_premium(self, obj):
        sub = getattr(obj, "subscription", None)
        return bool(sub and sub.is_premium)

    def get_is_free(self, obj):
        sub = getattr(obj, "subscription", None)
        return not bool(sub and sub.is_premium)


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
        
        sub = getattr(user, "subscription", None)
        token["plan"] = sub.plan if sub else "free_trial"
        token["is_premium"] = bool(sub and sub.is_premium)
        token["is_free"] = not bool(sub and sub.is_premium)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        
        sub = getattr(self.user, "subscription", None)
        data["plan"] = sub.plan if sub else "free_trial"
        data["is_premium"] = bool(sub and sub.is_premium)
        data["is_free"] = not bool(sub and sub.is_premium)
        
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


class ChangePasswordSerializer(serializers.Serializer):
    """Authenticated user changes their own password."""

    old_password = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        style={"input_type": "password"},
    )
    confirm_password = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "New passwords do not match."}
            )
        if attrs["old_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must differ from the old password."}
            )
        return attrs

class AdminStudentListSerializer(serializers.ModelSerializer):
    """One row of the admin Student table.

    Field names are kept aligned with the dashboard columns:
    Id, Student Name, Email, Class/Form, Plan, Status, Join Date.
    """

    student_name = serializers.CharField(source="full_name", read_only=True)
    # "4th Form", "5th Form", ... (human label from ClassLevel choices)
    class_form = serializers.CharField(
        source="get_student_class_display", read_only=True
    )
    # "Premium" / "Free" — derived from the annotated `is_premium` flag.
    plan = serializers.SerializerMethodField()
    # "Active" / "Inactive" — derived from is_active.
    status = serializers.SerializerMethodField()
    join_date = serializers.DateTimeField(source="date_joined", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "student_name",
            "email",
            "student_class",   # raw value, e.g. "4th"
            "class_form",      # display value, e.g. "4th Form"
            "plan",
            "status",
            "is_active",
            "join_date",
        ]
        read_only_fields = fields

    def get_plan(self, obj):
        return "Premium" if getattr(obj, "is_premium", False) else "Free"

    def get_status(self, obj):
        return "Active" if obj.is_active else "Inactive"

class StudentQuizAttemptSerializer(serializers.ModelSerializer):
    """One row of the student's quiz-history table (with leaderboard rank)."""

    quiz_name = serializers.CharField(source="quiz.title", read_only=True)
    percentage = serializers.FloatField(read_only=True)
    rank = serializers.IntegerField(read_only=True)  # attached in the view/serializer

    class Meta:
        model = Attempt
        fields = [
            "id",
            "quiz",
            "quiz_name",
            "score",
            "total",
            "percentage",
            "rank",
            "submitted_at",
        ]


class StudentSubscriptionInfoSerializer(serializers.ModelSerializer):
    """The "Subscription Information" block."""

    plan_type = serializers.CharField(source="get_plan_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    registration_date = serializers.DateTimeField(
        source="created_at", read_only=True
    )
    expiry_date = serializers.DateTimeField(
        source="current_period_end", read_only=True
    )
    is_premium = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "plan",
            "plan_type",
            "status",
            "status_display",
            "registration_date",
            "expiry_date",
            "is_premium",
        ]


class StudentPaymentInfoSerializer(serializers.ModelSerializer):
    """Latest payment for the "Payment" row (method / status)."""

    # "Paid" when the latest payment is complete, else the human status label.
    payment_status = serializers.SerializerMethodField()
    # NOTE: there is no payment_method column; pulled from raw_response if present.
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "order_id",
            "amount",
            "currency",
            "payment_method",
            "payment_status",
            "status",
            "created_at",
        ]

    def get_payment_status(self, obj):
        if obj.status == Payment.Status.COMPLETE:
            return "Paid"
        return obj.get_status_display()

    def get_payment_method(self, obj):
        raw = obj.raw_response or {}
        return raw.get("payment_method") or raw.get("paymentMethod") or "DimePay"


class AdminStudentDetailSerializer(serializers.ModelSerializer):
    """Full student profile for the admin detail screen."""

    # --- Header ---
    student_name = serializers.CharField(source="full_name", read_only=True)
    phone = serializers.CharField(source="contact_number", read_only=True)
    status = serializers.SerializerMethodField()
    join_date = serializers.DateTimeField(source="date_joined", read_only=True)
    plan_status = serializers.SerializerMethodField()

    # --- Personal information ---
    school = serializers.CharField(source="current_school", read_only=True)
    class_form = serializers.CharField(
        source="get_student_class_display", read_only=True
    )
    time_slot = serializers.CharField(
        source="get_preferred_time_display", read_only=True
    )

    # --- Composed blocks ---
    subscription = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    quick_summary = serializers.SerializerMethodField()
    quizzes = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            # header
            "id",
            "student_name",
            "email",
            "phone",
            "status",
            "is_active",
            "join_date",
            "plan_status",
            # personal information
            "full_name",
            "school",
            "student_class",
            "class_form",
            "time_slot",
            # parent information
            "parent_full_name",
            "parent_email",
            "parent_contact_number",
            # blocks
            "subscription",
            "payment",
            "quick_summary",
            "quizzes",
        ]
        read_only_fields = fields

    def get_status(self, obj):
        return "Active" if obj.is_active else "Inactive"

    def get_plan_status(self, obj):
        sub = getattr(obj, "subscription", None)
        return "Premium" if (sub and sub.is_premium) else "Free"

    def get_subscription(self, obj):
        sub = getattr(obj, "subscription", None)
        if sub is None:
            return None
        return StudentSubscriptionInfoSerializer(sub).data

    def get_payment(self, obj):
        latest = obj.payments.order_by("-created_at").first()
        if latest is None:
            return None
        return StudentPaymentInfoSerializer(latest).data

    def get_quick_summary(self, obj):
        agg = obj.attempts.aggregate(
            total_quizzes_taken=Count("id"),
            average_score=Avg(
                Case(
                    When(
                        total__gt=0,
                        then=ExpressionWrapper(
                            F("score") * 100.0 / F("total"),
                            output_field=FloatField(),
                        ),
                    ),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            ),
        )
        return {
            "total_quizzes_taken": agg["total_quizzes_taken"] or 0,
            "average_score": round(agg["average_score"] or 0.0, 2),
        }

    def get_quizzes(self, obj):
        attempts = list(
            obj.attempts.select_related("quiz").order_by("-submitted_at")
        )
        # Rank = position on that quiz's leaderboard (-score, then earliest submit).
        for attempt in attempts:
            attempt.rank = (
                Attempt.objects.filter(quiz=attempt.quiz)
                .filter(
                    Q(score__gt=attempt.score)
                    | Q(
                        score=attempt.score,
                        submitted_at__lt=attempt.submitted_at,
                    )
                )
                .count()
                + 1
            )
        return StudentQuizAttemptSerializer(attempts, many=True).data