# app/services/submission_service.py
"""
Submission business logic service
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from flask_smorest import abort
from sqlalchemy import select, func

from app.core.extensions import db
from app.models.question import Question, TestCase
from app.models.submission import Submission, TestResult
from app.services.executor_service import ExecutorService


class SubmissionService:
    """Submission management service"""

    @staticmethod
    def submit_problem_code(
        student_id: int,
        problem_id: int,
        language: str,
        code: str,
        time_limit_sec: float = 2.0
    ) -> Dict[str, Any]:
        from app.models.problem import Problem

        problem = Problem.query.get(problem_id)
        if not problem:
            abort(404, message="Problem not found")

        variant = problem.variant_for(language)
        if not variant:
            abort(404, message=f"No {language} variant available for this problem")

        return SubmissionService.submit_code(
            student_id=student_id,
            question_id=variant.id,
            code=code,
            time_limit_sec=time_limit_sec,
        )
    
    @staticmethod
    def submit_code(
        student_id: int,
        question_id: int,
        code: str,
        time_limit_sec: float = 2.0
    ) -> Dict[str, Any]:
        """
        Submit code and run tests
        
        Args:
            student_id: Student ID
            question_id: Question ID
            code: Submitted code
            time_limit_sec: Time limit (seconds)
            
        Returns:
            dict: Submission result
        """
        # Validate that the question exists
        question = Question.query.get(question_id)
        if not question:
            abort(404, message="Question not found")
        
        # Get programming language
        language = question.programming_language or "c"
        
        # Create submission record (initial status: running)
        submission = Submission(
            student_id=student_id,
            question_id=question_id,
            code=code,
            status="running",
            submitted_at=datetime.utcnow(),
        )
        db.session.add(submission)
        db.session.flush()  # Get submission.id
        
        test_cases = TestCase.query.filter_by(problem_id=question.problem_id).order_by(TestCase.id).all()
        if not test_cases:
            submission.status = "error"
            submission.score = 0.0
            db.session.commit()
            abort(400, message="No test cases for this problem")
        
        # Compute total weight
        total_weight = sum(tc.weight or 1.0 for tc in test_cases) or 1.0
        earned_weight = 0.0
        
        # Run each test case one by one
        test_results = []
        has_error = False
        
        for tc in test_cases:
            try:
                result = ExecutorService.run_code(
                    code=code,
                    language=language,
                    stdin_text=tc.input or "",
                    expected_output=tc.expected_output or "",
                    time_limit_sec=time_limit_sec,
                )
                
                # Determine status
                status = result.get("status", "UNKNOWN")
                passed = bool(result.get("passed", False))
                
                # Create test result record
                test_result = TestResult(
                    submission_id=submission.id,
                    test_case_id=tc.id,
                    passed=passed,
                    actual_output=result.get("stdout", ""),
                    error_message=result.get("stderr", "") or result.get("error_message", ""),
                    execution_time=(result.get("time_ms", 0) or 0) / 1000.0,  # ms -> s
                )
                db.session.add(test_result)
                test_results.append((test_result, tc, result))
                
                # Accumulate earned weight
                if test_result.passed:
                    earned_weight += (tc.weight or 1.0)
                    
                # Check for compilation or system errors
                if status in ["CE", "SYSTEM_ERROR"]:
                    has_error = True
                    break  # Stop running further tests on compilation error
                    
            except Exception as e:
                # Execution error, record the error
                test_result = TestResult(
                    submission_id=submission.id,
                    test_case_id=tc.id,
                    passed=False,
                    actual_output="",
                    error_message=f"Execution error: {str(e)}",
                    execution_time=0.0,
                )
                db.session.add(test_result)
                test_results.append((test_result, tc, {"status": "SYSTEM_ERROR", "error": str(e)}))
                has_error = True
                break
        
        # Compute total score and update submission status
        submission.score = round(100.0 * earned_weight / total_weight, 2) if not has_error else 0.0
        submission.status = "error" if has_error else "completed"
        db.session.commit()
        
        # Build response payload
        cases_output = []
        for idx, (test_result, test_case, exec_result) in enumerate(test_results, start=1):
            case_data = SubmissionService._format_case_result(
                index=idx,
                test_result=test_result,
                test_case=test_case,
                exec_result=exec_result
            )
            cases_output.append(case_data)
        
        return {
            "id": submission.id,
            "problem_id": question.problem_id,
            "question_id": submission.question_id,
            "language": language,
            "status": submission.status,
            "score": submission.score,
            "cases": cases_output
        }
    
    @staticmethod
    def get_student_submissions(
        student_id: int,
        question_id: Optional[int] = None, 
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get a list of submissions for a student
        
        Args:
            student_id: Student ID
            question_id: Optional, filter by a specific question
            limit: Maximum number of records to return
            offset: Offset for pagination
            
        Returns:
            dict: Submission list
        """
        from app.models.problem import Problem

        query = (
            db.session.query(Submission, Question, Problem)
            .join(Question, Submission.question_id == Question.id)
            .join(Problem, Question.problem_id == Problem.id)
            .filter(Submission.student_id == student_id)
        )
        
        if question_id:
            query = query.filter(Submission.question_id == question_id)
        
        query = query.order_by(Submission.submitted_at.desc())
        
        # Get total count
        total = query.count()
        
        # Apply pagination
        rows = query.limit(limit).offset(offset).all()
        
        items = []
        for submission, question, problem in rows:
            items.append({
                "id": submission.id,
                "problem_id": problem.id,
                "question_id": submission.question_id,
                "question_title": problem.title,
                "language": question.programming_language,
                "status": submission.status,
                "score": submission.score,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
            })
        
        return {
            "items": items,
            "total": total
        }
    
    @staticmethod
    def get_submission_detail(
        submission_id: int,
        user_id: int,
        user_role: str
    ) -> Dict[str, Any]:
        """
        Get submission details (including all test case results)
        
        Args:
            submission_id: Submission ID
            user_id: Current user ID
            user_role: User role (student/teacher)
            
        Returns:
            dict: Submission details
        """
        submission = Submission.query.get(submission_id)
        if not submission:
            abort(404, message="Submission not found")
        
        # Students can only view their own submissions
        if user_role == "student" and submission.student_id != user_id:
            abort(403, message="You can only view your own submissions")
        
        # Get question title
        question = Question.query.get(submission.question_id)
        problem = question.problem if question else None
        question_title = problem.title if problem else None
        
        # Get test results
        test_results = (
            TestResult.query
            .filter_by(submission_id=submission.id)
            .order_by(TestResult.id.asc())
            .all()
        )
        
        # Get related test cases (used to determine hidden status)
        test_case_ids = [tr.test_case_id for tr in test_results]
        test_cases = TestCase.query.filter(TestCase.id.in_(test_case_ids)).all()
        case_map = {tc.id: tc for tc in test_cases}
        
        # Build list of test case results
        cases_output = []
        for idx, test_result in enumerate(test_results, start=1):
            test_case = case_map.get(test_result.test_case_id)
            case_data = SubmissionService._format_case_result_from_db(
                index=idx,
                test_result=test_result,
                test_case=test_case
            )
            cases_output.append(case_data)
        
        return {
            "id": submission.id,
            "problem_id": problem.id if problem else None,
            "question_id": submission.question_id,
            "question_title": question_title,
            "language": question.programming_language if question else None,
            "code": submission.code,
            "status": submission.status,
            "score": submission.score,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
            "cases": cases_output
        }
    
    @staticmethod
    def check_submission_exists(student_id: int, question_id: int) -> Dict[str, Any]:
        """
        Check whether a user has any submissions for a given question
        
        Args:
            student_id: Student ID
            question_id: Question ID
        
        Returns:
            dict: {"has_submitted": bool, "submission_count": int}
        """
        count = db.session.execute(
            select(func.count(Submission.id))
            .where(
                Submission.student_id == student_id,
                Submission.question_id == question_id
            )
        ).scalar()
        
        return {
            "has_submitted": count > 0,
            "submission_count": count
        }
    
    @staticmethod
    def _format_case_result(
        index: int,
        test_result: TestResult,
        test_case: TestCase,
        exec_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Format test case result (used when submitting)
        
        Args:
            index: Case index
            test_result: TestResult object
            test_case: TestCase object
            exec_result: Execution result dictionary
            
        Returns:
            dict: Formatted case result
        """
        is_hidden = bool(test_case.is_hidden)
        status = exec_result.get("status", "UNKNOWN")
        if not test_result.passed:
            if status in ["CE", "RE", "TLE"]:
                status = status
            else:
                status = "WA"
        else:
            status = "AC"
        
        return {
            "index": index,
            "test_case_id": test_case.id,
            "status": status,
            "passed": test_result.passed,
            "time_ms": exec_result.get("time_ms"),
            "input": None if is_hidden else (test_case.input or ""),
            "expected": None if is_hidden else (test_case.expected_output or ""),
            "output": test_result.actual_output or "",
            "stderr": test_result.error_message or "",
            "hidden": is_hidden,
            "weight": float(test_case.weight or 1.0)
        }
    
    @staticmethod
    def _format_case_result_from_db(
        index: int,
        test_result: TestResult,
        test_case: Optional[TestCase]
    ) -> Dict[str, Any]:
        """
        Format test case result (used when querying history)
        
        Args:
            index: Case index
            test_result: TestResult object
            test_case: TestCase object (may be None)
            
        Returns:
            dict: Formatted case result
        """
        is_hidden = bool(test_case.is_hidden) if test_case else True
        
        return {
            "index": index,
            "test_case_id": test_result.test_case_id,
            "status": "AC" if test_result.passed else "WA",
            "passed": test_result.passed,
            "time_ms": int((test_result.execution_time or 0.0) * 1000),  # s -> ms
            "input": None if is_hidden else (test_case.input or "" if test_case else ""),
            "expected": None if is_hidden else (test_case.expected_output or "" if test_case else ""),
            "output": test_result.actual_output or "",
            "stderr": test_result.error_message or "",
            "hidden": is_hidden,
            "weight": float(test_case.weight or 1.0) if test_case else 1.0
        }
