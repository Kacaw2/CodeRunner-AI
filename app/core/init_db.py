#!/usr/bin/env python3
"""
Database Initialization Script

Usage:
    python init_db.py          # Create all tables
    python scripts/init_db.py --drop   # Drop all tables and recreate
    python scripts/init_db.py --seed   # Add test data
"""
import sys
import os
import argparse
import re
from datetime import timedelta

# Add project root directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from app.core.extensions import db
from app.core.timezone import now_china
from app.models.user import User, UserRole
from app.models.classroom import Classroom, Enrollment
from app.models.problem import Problem
from app.models.quiz import Quiz, QuizProblem, ClassroomQuiz
from app.models.question import Question, TestCase


def canonical_problem_title(title):
    title = (title or '').strip()
    for suffix in (' (C)', ' (c)', ' - C', ' - c'):
        if title.endswith(suffix):
            return title[:-len(suffix)].strip()
    return title


def slugify_problem(title, fallback_id):
    base = re.sub(r'[^a-z0-9]+', '-', (title or '').lower()).strip('-')
    return base or f'problem-{fallback_id}'

def check_tables_exist():
    """Check if any tables exist in the database"""
    from sqlalchemy import text
    try:
        result = db.session.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
        ))
        count = result.scalar()
        return count > 0
    except Exception as e:
        print(f"Warning: Could not check existing tables: {e}")
        return False
    
def drop_all():
    """Drop all tables"""
    print("Dropping all tables...")
    
    from sqlalchemy import text
    
    try:
        db_url = str(db.engine.url)
        is_mysql = 'mysql' in db_url
        
        if is_mysql:
            print("   • Disabling foreign key checks (MySQL)...")
            db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
            db.session.commit()
        
        # delete all tables
        print("   • Dropping tables...")
        db.drop_all()
        
        if is_mysql:
            print("   • Re-enabling foreign key checks (MySQL)...")
            db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))
            db.session.commit()
        
        print("✓ All tables dropped successfully")
        
    except Exception as e:
        print(f"Error during drop: {e}")
        
        try:
            if is_mysql:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))
                db.session.commit()
        except:
            pass
        
        raise


def create_all():
    """Create all tables"""
    print("Creating all tables...")
    db.create_all()
    print("✓ All tables created")


def seed_data():
    """Add test data"""
    print("Seeding test data...")
    
    try:
        # ============================================
        # 1. Create User Accounts
        # ============================================
        print("\nCreating users...")
        
        # Admin account
        admin = User(
            username='admin',
            password='scrypt:32768:8:1$gEMt6gvkLNu5t61P$5bace68ea63a955ae77395be51d19d860af462ee6e48cc142ca8331b386f21c5e0ac2077a9b05e122c94e6b9de8b9c2700cede1b34f96985a37ca56d87603a4e',
            email='admin@example.com',
            role=UserRole.ADMIN
        )
        db.session.add(admin)
        
        # Teacher accounts
        teachers = []
        for i in range(1, 4):
            teacher = User(
                username=f'teacher{i}',
                password='scrypt:32768:8:1$gEMt6gvkLNu5t61P$5bace68ea63a955ae77395be51d19d860af462ee6e48cc142ca8331b386f21c5e0ac2077a9b05e122c94e6b9de8b9c2700cede1b34f96985a37ca56d87603a4e',
                email=f'teacher{i}@example.com',
                role=UserRole.TEACHER
            )
            db.session.add(teacher)
            teachers.append(teacher)
        
        # Student accounts
        students = []
        for i in range(1, 9):
            student = User(
                username=f'student{i}',
                password='scrypt:32768:8:1$gEMt6gvkLNu5t61P$5bace68ea63a955ae77395be51d19d860af462ee6e48cc142ca8331b386f21c5e0ac2077a9b05e122c94e6b9de8b9c2700cede1b34f96985a37ca56d87603a4e',
                email=f'student{i}@example.com',
                role=UserRole.STUDENT
            )
            db.session.add(student)
            students.append(student)
        
        db.session.commit()
        print("✓ Users created:")
        print(f"  - admin/admin123 (Admin)")
        print(f"  - teacher1-3/admin123 (Teachers: {len(teachers)})")
        print(f"  - student1-8/admin123 (Students: {len(students)})")
        
        # ============================================
        # 2. Create Classrooms
        # ============================================
        print("\nCreating classrooms...")
        
        classrooms_data = [
            {
                'name': 'Python Programming 101',
                'code': 'PY101A',
                'description': 'Introduction to Python Programming for beginners',
                'teacher': teachers[0]
            },
            {
                'name': 'Advanced Python Development',
                'code': 'PY201A',
                'description': 'Advanced Python concepts and best practices',
                'teacher': teachers[0]
            },
            {
                'name': 'C Programming Fundamentals',
                'code': 'C101A',
                'description': 'Learn C programming from scratch',
                'teacher': teachers[1]
            },
            {
                'name': 'Data Structures in C',
                'code': 'C201A',
                'description': 'Implementing data structures using C',
                'teacher': teachers[1]
            },
            {
                'name': 'Programming Workshop',
                'code': 'WS101',
                'description': 'Mixed programming practice workshop',
                'teacher': teachers[2]
            }
        ]
        
        classrooms = []
        for cls_data in classrooms_data:
            classroom = Classroom(
                name=cls_data['name'],
                code=cls_data['code'],
                description=cls_data['description'],
                teacher_id=cls_data['teacher'].id
            )
            db.session.add(classroom)
            classrooms.append(classroom)
        
        db.session.commit()
        print(f"✓ {len(classrooms)} classrooms created")
        
        # ============================================
        # 3. Enroll Students in Classrooms
        # ============================================
        print("\nEnrolling students...")
        
        enrollments = [
            *[(students[i], classrooms[0]) for i in range(6)],
            *[(students[i], classrooms[1]) for i in range(2, 6)],
            *[(students[i], classrooms[2]) for i in range(1, 6)],
            *[(students[i], classrooms[3]) for i in range(3, 6)],
            *[(student, classrooms[4]) for student in students],
        ]
        
        enrollment_count = 0
        for student, classroom in enrollments:
            enrollment = Enrollment(
                student_id=student.id,
                classroom_id=classroom.id
            )
            db.session.add(enrollment)
            enrollment_count += 1
        
        db.session.commit()
        print(f"✓ {enrollment_count} enrollments created")
        
        # ============================================
        # 4. Create Quizzes
        # ============================================
        print("\nCreating quizzes...")
        
        quizzes_data = [
            {
                'title': 'Python Basics Quiz',
                'description': 'Test your fundamental Python knowledge',
                'teacher': teachers[0],
                'duration': 60,
                'published': True
            },
            {
                'title': 'Python Advanced Quiz',
                'description': 'Advanced Python programming challenges',
                'teacher': teachers[0],
                'duration': 90,
                'published': True
            },
            {
                'title': 'C Language Fundamentals',
                'description': 'Basic C programming test',
                'teacher': teachers[1],
                'duration': 60,
                'published': True
            },
            {
                'title': 'C Language Advanced',
                'description': 'Advanced C programming challenges',
                'teacher': teachers[1],
                'duration': 90,
                'published': True
            },
        ]
        
        quizzes = []
        for quiz_data in quizzes_data:
            quiz = Quiz(
                title=quiz_data['title'],
                description=quiz_data['description'],
                created_by=quiz_data['teacher'].id,
                duration_minutes=quiz_data['duration'],
                is_published=quiz_data['published']
            )
            db.session.add(quiz)
            quizzes.append(quiz)
        
        db.session.commit()
        print(f"✓ {len(quizzes)} quizzes created")
        
        # ============================================
        # 5. Assign Quizzes to Classrooms
        # ============================================
        print("\nAssigning quizzes to classrooms...")
        
        assignments = [
            (classrooms[0], quizzes[0], teachers[0], now_china() + timedelta(days=7)),
            (classrooms[1], quizzes[1], teachers[0], now_china() + timedelta(days=14)),
            (classrooms[2], quizzes[2], teachers[1], now_china() + timedelta(days=7)),
            (classrooms[3], quizzes[3], teachers[1], now_china() + timedelta(days=14)),
        ]
        
        for classroom, quiz, teacher, due_date in assignments:
            cq = ClassroomQuiz(
                classroom_id=classroom.id,
                quiz_id=quiz.id,
                assigned_by=teacher.id,
                due_date=due_date,
                allow_late_submission=True
            )
            db.session.add(cq)
        
        db.session.commit()
        print(f"✓ {len(assignments)} quiz assignments created")
        
        # ============================================
        # 6. Create Questions (30道OJ模式题目)
        # ============================================
        print("\nCreating questions...")
        
        questions_data = [
            # ============================================
            # Python 基础题 (8题)
            # ============================================
            {
                'quiz': quizzes[0],
                'title': 'Add Two Numbers',
                'description': '''Read two integers from input and output their sum.

Example:
    Input:
        5 3
    Output:
        8
    
    Input:
        -10 20
    Output:
        10''',
                'order': 1,
                'points': 5,
                'starter_code': '''# Read input and calculate sum
# Your code here''',
                'solution': '''a, b = map(int, input().split())
print(a + b)''',
                'solution_explanation': '''This solution reads two space-separated integers using input().split() and converts them to integers using map(). It then outputs their sum using print().''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('5 3', '8', False, 0.5),
                    ('-10 20', '10', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Reverse a String',
                'description': '''Read a string from input and output it reversed.

Example:
    Input:
        hello
    Output:
        olleh
    
    Input:
        Python
    Output:
        nohtyP''',
                'order': 2,
                'points': 10,
                'starter_code': '''# Read input and reverse string
# Your code here''',
                'solution': '''s = input().rstrip("\\n")
print(s[::-1])''',
                'solution_explanation': '''This solution reads a string from input, removes the trailing newline character using rstrip(), and reverses it using Python's slice notation [::-1]. The reversed string is then printed to stdout.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('hello', 'olleh', False, 0.5),
                    ('Python', 'nohtyP', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Find Maximum in List',
                'description': '''Read a list of integers and output the maximum value.
Do not use the built-in max() function.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        7
        3 1 4 1 5 9 2
    Output:
        9
    
    Input:
        4
        -5 -2 -8 -1
    Output:
        -1''',
                'order': 3,
                'points': 10,
                'starter_code': '''# Read input and find maximum
# Your code here''',
                'solution': '''n = int(input())
numbers = list(map(int, input().split()))
max_num = numbers[0]
for num in numbers:
    if num > max_num:
        max_num = num
print(max_num)''',
                'solution_explanation': '''This solution first reads the number of elements, then reads the list of integers. It initializes max_num with the first element and iterates through all numbers, updating max_num whenever a larger number is found. Finally, it prints the maximum value.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('7\\n3 1 4 1 5 9 2', '9', False, 0.5),
                    ('4\\n-5 -2 -8 -1', '-1', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Calculate Average',
                'description': '''Read a list of numbers and output their average rounded to 1 decimal place.

Input format:
    First line: number of elements
    Second line: space-separated numbers

Example:
    Input:
        4
        10 20 30 40
    Output:
        25.0
    
    Input:
        5
        1 2 3 4 5
    Output:
        3.0''',
                'order': 4,
                'points': 10,
                'starter_code': '''# Read input and calculate average
# Your code here''',
                'solution': '''n = int(input())
numbers = list(map(int, input().split()))
average = sum(numbers) / len(numbers)
print(f"{average:.1f}")''',
                'solution_explanation': '''This solution reads the number of elements and the list of numbers. It calculates the average using sum() and len(), then formats the output to one decimal place using f-string formatting with :.1f.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('4\\n10 20 30 40', '25.0', False, 0.5),
                    ('5\\n1 2 3 4 5', '3.0', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Count Vowels',
                'description': '''Read a string and output the number of vowels (a, e, i, o, u) in it.
The function should be case-insensitive.

Example:
    Input:
        Hello World
    Output:
        3
    
    Input:
        Python Programming
    Output:
        5''',
                'order': 5,
                'points': 10,
                'starter_code': '''# Read input and count vowels
# Your code here''',
                'solution': '''s = input().rstrip("\\n")
vowels = 'aeiouAEIOU'
count = sum(1 for char in s if char in vowels)
print(count)''',
                'solution_explanation': '''This solution reads a string from input and counts the vowels by using a generator expression with sum(). It checks each character against the vowels string (which includes both lowercase and uppercase vowels) and counts the matches.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('Hello World', '3', False, 0.5),
                    ('Python Programming', '5', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Check Palindrome',
                'description': '''Read a string and output True if it is a palindrome, False otherwise.
A palindrome reads the same forward and backward (case-insensitive).

Example:
    Input:
        racecar
    Output:
        True
    
    Input:
        hello
    Output:
        False''',
                'order': 6,
                'points': 15,
                'starter_code': '''# Read input and check palindrome
# Your code here''',
                'solution': '''s = input().rstrip("\\n").lower()
print(s == s[::-1])''',
                'solution_explanation': '''This solution reads a string, converts it to lowercase for case-insensitive comparison, and checks if it equals its reverse using slice notation [::-1]. The boolean result is directly printed.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('racecar', 'True', False, 0.5),
                    ('hello', 'False', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Sum of List',
                'description': '''Read a list of integers and output their sum.
Do not use the built-in sum() function.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        5
        1 2 3 4 5
    Output:
        15
    
    Input:
        3
        10 -5 3
    Output:
        8''',
                'order': 7,
                'points': 10,
                'starter_code': '''# Read input and calculate sum
# Your code here''',
                'solution': '''n = int(input())
numbers = list(map(int, input().split()))
total = 0
for num in numbers:
    total += num
print(total)''',
                'solution_explanation': '''This solution reads the number of elements and the list of integers. It initializes a total variable to 0 and iterates through all numbers, adding each to the total. Finally, it prints the sum.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('5\\n1 2 3 4 5', '15', False, 0.5),
                    ('3\\n10 -5 3', '8', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[0],
                'title': 'Calculate Factorial',
                'description': '''Read a non-negative integer and output its factorial.

Example:
    Input:
        5
    Output:
        120
    
    Input:
        0
    Output:
        1''',
                'order': 8,
                'points': 15,
                'starter_code': '''# Read input and calculate factorial
# Your code here''',
                'solution': '''n = int(input())
result = 1
for i in range(2, n + 1):
    result *= i
print(result)''',
                'solution_explanation': '''This solution reads an integer n and calculates its factorial iteratively. It initializes result to 1 and multiplies it by all integers from 2 to n. For n=0 or n=1, the loop doesn't execute and returns 1, which is correct.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('5', '120', False, 0.5),
                    ('7', '5040', True, 0.5)
                ]
            },
            # ============================================
            # Python 进阶题 (7题)
            # ============================================
            {
                'quiz': quizzes[1],
                'title': 'Fibonacci Number',
                'description': '''Read an integer n and output the nth Fibonacci number.
The Fibonacci sequence: 0, 1, 1, 2, 3, 5, 8, 13, ...

Example:
    Input:
        6
    Output:
        8
    
    Input:
        10
    Output:
        55''',
                'order': 1,
                'points': 20,
                'starter_code': '''# Read input and calculate Fibonacci number
# Your code here''',
                'solution': '''n = int(input())
if n <= 1:
    print(n)
else:
    prev2, prev1 = 0, 1
    for i in range(2, n + 1):
        current = prev1 + prev2
        prev2 = prev1
        prev1 = current
    print(prev1)''',
                'solution_explanation': '''This solution uses an iterative approach to calculate the nth Fibonacci number. For n <= 1, it directly outputs n. Otherwise, it maintains two previous values (prev2 and prev1) and iteratively calculates the next Fibonacci number by adding them together, updating the previous values in each iteration.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('6', '8', False, 0.5),
                    ('10', '55', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Check Prime Number',
                'description': '''Read an integer and output True if it is prime, False otherwise.
A prime number is only divisible by 1 and itself.

Example:
    Input:
        7
    Output:
        True
    
    Input:
        12
    Output:
        False''',
                'order': 2,
                'points': 20,
                'starter_code': '''# Read input and check if prime
# Your code here''',
                'solution': '''n = int(input())
if n < 2:
    print(False)
else:
    is_prime = True
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            is_prime = False
            break
    print(is_prime)''',
                'solution_explanation': '''This solution checks if a number is prime by testing divisibility from 2 to the square root of n. If n < 2, it's not prime. Otherwise, it checks each divisor; if any divides n evenly, it's not prime. The optimization of checking only up to sqrt(n) reduces time complexity to O(√n).''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('7', 'True', False, 0.5),
                    ('12', 'False', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Remove Duplicates',
                'description': '''Read a list and output it with duplicates removed while maintaining order.

Input format:
    First line: number of elements
    Second line: space-separated elements

Example:
    Input:
        7
        1 2 2 3 4 4 5
    Output:
        1 2 3 4 5
    
    Input:
        4
        a b a c
    Output:
        a b c''',
                'order': 3,
                'points': 15,
                'starter_code': '''# Read input and remove duplicates
# Your code here''',
                'solution': '''n = int(input())
elements = input().split()
seen = []
for item in elements:
    if item not in seen:
        seen.append(item)
print(' '.join(seen))''',
                'solution_explanation': '''This solution reads the elements as strings and maintains a list of seen elements. It iterates through the input elements, adding each one to the seen list only if it hasn't been encountered before. This preserves the original order while removing duplicates. Finally, it joins the elements with spaces for output.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('7\\n1 2 2 3 4 4 5', '1 2 3 4 5', False, 0.5),
                    ('4\\na b a c', 'a b c', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Two Sum',
                'description': '''Given an array of integers and a target, output indices of two numbers that add up to target.
You may assume that each input has exactly one solution.

Input format:
    First line: number of elements and target (space-separated)
    Second line: space-separated integers

Example:
    Input:
        4 9
        2 7 11 15
    Output:
        0 1
    
    Input:
        3 6
        3 2 4
    Output:
        1 2''',
                'order': 4,
                'points': 25,
                'starter_code': '''# Read input and find two sum indices
# Your code here''',
                'solution': '''n, target = map(int, input().split())
nums = list(map(int, input().split()))
seen = {}
for i, num in enumerate(nums):
    complement = target - num
    if complement in seen:
        print(seen[complement], i)
        break
    seen[num] = i''',
                'solution_explanation': '''This solution uses a hash map (dictionary) to achieve O(n) time complexity. For each number, it calculates the complement (target - num) and checks if the complement exists in the seen dictionary. If found, it outputs the indices. Otherwise, it stores the current number and its index for future lookups.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('4 9\\n2 7 11 15', '0 1', False, 0.5),
                    ('3 6\\n3 2 4', '1 2', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Merge Sorted Lists',
                'description': '''Merge two sorted lists into one sorted list.

Input format:
    First line: size of first list
    Second line: first sorted list (space-separated)
    Third line: size of second list
    Fourth line: second sorted list (space-separated)

Example:
    Input:
        3
        1 3 5
        3
        2 4 6
    Output:
        1 2 3 4 5 6
    
    Input:
        2
        1 2
        2
        3 4
    Output:
        1 2 3 4''',
                'order': 5,
                'points': 25,
                'starter_code': '''# Read input and merge sorted lists
# Your code here''',
                'solution': '''n1 = int(input())
list1 = list(map(int, input().split()))
n2 = int(input())
list2 = list(map(int, input().split()))
result = []
i, j = 0, 0
while i < len(list1) and j < len(list2):
    if list1[i] < list2[j]:
        result.append(list1[i])
        i += 1
    else:
        result.append(list2[j])
        j += 1
result.extend(list1[i:])
result.extend(list2[j:])
print(' '.join(map(str, result)))''',
                'solution_explanation': '''This solution uses the two-pointer technique to merge two sorted lists efficiently in O(n+m) time. It maintains pointers i and j for both lists, comparing elements and adding the smaller one to the result. After one list is exhausted, it extends the result with the remaining elements from the other list.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('3\\n1 3 5\\n3\\n2 4 6', '1 2 3 4 5 6', False, 0.5),
                    ('2\\n1 2\\n2\\n3 4', '1 2 3 4', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Longest Common Prefix',
                'description': '''Find the longest common prefix string amongst an array of strings.
If there is no common prefix, output empty.

Input format:
    First line: number of strings
    Following lines: one string per line

Example:
    Input:
        3
        flower
        flow
        flight
    Output:
        fl
    
    Input:
        3
        dog
        racecar
        car
    Output:
        ''',
                'order': 6,
                'points': 30,
                'starter_code': '''# Read input and find longest common prefix
# Your code here''',
                'solution': '''n = int(input())
strings = [input().rstrip("\\n") for _ in range(n)]
if not strings:
    print("")
else:
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                break
    print(prefix)''',
                'solution_explanation': '''This solution starts with the first string as the initial prefix. For each subsequent string, it shortens the prefix by removing characters from the end until the string starts with the prefix. If the prefix becomes empty, there's no common prefix. This approach is efficient and handles edge cases well.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('3\\nflower\\nflow\\nflight', 'fl', False, 0.5),
                    ('3\\ndog\\nracecar\\ncar', '', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[1],
                'title': 'Valid Parentheses',
                'description': '''Check if a string of parentheses is valid.
Valid means every opening bracket has a corresponding closing bracket in correct order.

Example:
    Input:
        ()
    Output:
        True
    
    Input:
        ([)]
    Output:
        False''',
                'order': 7,
                'points': 30,
                'starter_code': '''# Read input and check valid parentheses
# Your code here''',
                'solution': '''s = input().rstrip("\\n")
stack = []
mapping = {')': '(', '}': '{', ']': '['}
valid = True
for char in s:
    if char in mapping:
        if not stack or stack.pop() != mapping[char]:
            valid = False
            break
    else:
        stack.append(char)
if stack:
    valid = False
print(valid)''',
                'solution_explanation': '''This solution uses a stack to track opening brackets. For each closing bracket, it checks if the top of the stack has the matching opening bracket. If the stack is empty when encountering a closing bracket, or if brackets don't match, or if the stack is not empty at the end, the parentheses are invalid. This approach has O(n) time complexity.''',
                'language': 'python',
                'created_by': '2',
                'test_cases': [
                    ('()', 'True', False, 0.5),
                    ('([)]', 'False', True, 0.5)
                ]
            },
            # ============================================
            # C 基础题 (8题)
            # ============================================
            {
                'quiz': quizzes[2],
                'title': 'Add Two Numbers (C)',
                'description': '''Read two integers from input and output their sum.

Example:
    Input:
        5 3
    Output:
        8
    
    Input:
        -10 20
    Output:
        10''',
                'order': 1,
                'points': 5,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate sum
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int a, b;
    scanf("%d %d", &a, &b);
    printf("%d\\n", a + b);
    return 0;
}''',
                'solution_explanation': '''This solution uses scanf() to read two integers from standard input and printf() to output their sum. The format specifier %d is used for integer input/output.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('5 3', '8', False, 0.5),
                    ('-10 20', '10', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Find Maximum (C)',
                'description': '''Read an array of integers and output the maximum value.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        7
        3 1 4 1 5 9 2
    Output:
        9
    
    Input:
        4
        -5 -2 -8 -1
    Output:
        -1''',
                'order': 2,
                'points': 10,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and find maximum
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int max = arr[0];
    for (i = 1; i < n; i++) {
        if (arr[i] > max) {
            max = arr[i];
        }
    }
    printf("%d\\n", max);
    return 0;
}''',
                'solution_explanation': '''This solution reads the array size, then reads all elements into an array. It initializes max with the first element and iterates through the remaining elements, updating max whenever a larger value is found. Finally, it prints the maximum value.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('7\\n3 1 4 1 5 9 2', '9', False, 0.5),
                    ('4\\n-5 -2 -8 -1', '-1', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Calculate Average (C)',
                'description': '''Read an array of integers and output their average.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        4
        10 20 30 40
    Output:
        25.0
    
    Input:
        5
        1 2 3 4 5
    Output:
        3.0''',
                'order': 3,
                'points': 10,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate average
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int sum = 0;
    for (i = 0; i < n; i++) {
        sum += arr[i];
    }
    float average = (float)sum / n;
    printf("%.1f\\n", average);
    return 0;
}''',
                'solution_explanation': '''This solution reads the array size and elements, calculates the sum by iterating through all elements, then divides by the count to get the average. The sum is cast to float before division to ensure floating-point arithmetic. The result is formatted to one decimal place using %.1f.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('4\\n10 20 30 40', '25.0', False, 0.5),
                    ('5\\n1 2 3 4 5', '3.0', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'String Length (C)',
                'description': '''Read a string and output its length without using strlen().

Example:
    Input:
        hello
    Output:
        5
    
    Input:
        Python
    Output:
        6''',
                'order': 4,
                'points': 10,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate length
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    char str[1000];
    scanf("%s", str);
    int len = 0;
    while (str[len] != '\\0') {
        len++;
    }
    printf("%d\\n", len);
    return 0;
}''',
                'solution_explanation': '''This solution reads a string using scanf() and calculates its length by counting characters until the null terminator ('\\0') is reached. The while loop increments len for each character, effectively computing the string length without using the strlen() function.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('hello', '5', False, 0.5),
                    ('Python', '6', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Array Sum (C)',
                'description': '''Read an array of integers and output their sum.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        5
        1 2 3 4 5
    Output:
        15
    
    Input:
        3
        10 -5 3
    Output:
        8''',
                'order': 5,
                'points': 10,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate sum
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int sum = 0;
    for (i = 0; i < n; i++) {
        sum += arr[i];
    }
    printf("%d\\n", sum);
    return 0;
}''',
                'solution_explanation': '''This solution reads the array size and elements, then iterates through all elements to calculate their sum. It initializes sum to 0 and adds each array element to it. Finally, it prints the total sum.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('5\\n1 2 3 4 5', '15', False, 0.5),
                    ('3\\n10 -5 3', '8', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Factorial (C)',
                'description': '''Read a non-negative integer and output its factorial.

Example:
    Input:
        5
    Output:
        120
    
    Input:
        7
    Output:
        5040''',
                'order': 6,
                'points': 15,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate factorial
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    long long result = 1;
    for (i = 2; i <= n; i++) {
        result *= i;
    }
    printf("%lld\\n", result);
    return 0;
}''',
                'solution_explanation': '''This solution reads an integer n and calculates its factorial iteratively. It uses long long to handle larger factorial values. The loop multiplies result by each integer from 2 to n. For n=0 or n=1, the loop doesn't execute and returns 1, which is correct.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('5', '120', False, 0.5),
                    ('7', '5040', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Fibonacci (C)',
                'description': '''Read an integer n and output the nth Fibonacci number.
The Fibonacci sequence: 0, 1, 1, 2, 3, 5, 8, 13, ...

Example:
    Input:
        6
    Output:
        8
    
    Input:
        10
    Output:
        55''',
                'order': 7,
                'points': 20,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and calculate Fibonacci number
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    if (n <= 1) {
        printf("%d\\n", n);
    } else {
        int prev2 = 0, prev1 = 1, current;
        for (i = 2; i <= n; i++) {
            current = prev1 + prev2;
            prev2 = prev1;
            prev1 = current;
        }
        printf("%d\\n", prev1);
    }
    return 0;
}''',
                'solution_explanation': '''This solution uses an iterative approach to calculate the nth Fibonacci number. For n <= 1, it directly outputs n. Otherwise, it maintains two previous values and iteratively calculates the next Fibonacci number by adding them together, updating the previous values in each iteration.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('6', '8', False, 0.5),
                    ('10', '55', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[2],
                'title': 'Check Prime (C)',
                'description': '''Read an integer and output 1 if it is prime, 0 otherwise.

Example:
    Input:
        7
    Output:
        1
    
    Input:
        12
    Output:
        0''',
                'order': 8,
                'points': 20,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and check if prime
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>
#include <math.h>

int main() {
    int n, i;
    scanf("%d", &n);
    if (n < 2) {
        printf("0\\n");
    } else {
        int is_prime = 1;
        for (i = 2; i <= sqrt(n); i++) {
            if (n % i == 0) {
                is_prime = 0;
                break;
            }
        }
        printf("%d\\n", is_prime);
    }
    return 0;
}''',
                'solution_explanation': '''This solution checks if a number is prime by testing divisibility from 2 to the square root of n. If n < 2, it's not prime (outputs 0). Otherwise, it checks each potential divisor; if any divides n evenly, it sets is_prime to 0 and breaks. The optimization of checking only up to sqrt(n) reduces time complexity.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('7', '1', False, 0.5),
                    ('12', '0', True, 0.5)
                ]
            },
            # ============================================
            # C 进阶题 (7题)
            # ============================================
            {
                'quiz': quizzes[3],
                'title': 'Reverse Array (C)',
                'description': '''Read an array and output it reversed.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        5
        1 2 3 4 5
    Output:
        5 4 3 2 1
    
    Input:
        3
        10 20 30
    Output:
        30 20 10''',
                'order': 1,
                'points': 15,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and reverse array
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int left = 0, right = n - 1;
    while (left < right) {
        int temp = arr[left];
        arr[left] = arr[right];
        arr[right] = temp;
        left++;
        right--;
    }
    for (i = 0; i < n; i++) {
        printf("%d", arr[i]);
        if (i < n - 1) printf(" ");
    }
    printf("\\n");
    return 0;
}''',
                'solution_explanation': '''This solution reverses an array in-place using the two-pointer technique. It reads the array, then swaps elements from both ends moving towards the center. The left pointer starts at 0 and the right pointer starts at n-1. In each iteration, elements are swapped and pointers move towards each other until they meet.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('5\\n1 2 3 4 5', '5 4 3 2 1', False, 0.5),
                    ('3\\n10 20 30', '30 20 10', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'Find Element (C)',
                'description': '''Read an array and a target value, output the index of the target.
Return -1 if not found.

Input format:
    First line: number of elements and target (space-separated)
    Second line: space-separated integers

Example:
    Input:
        4 30
        10 20 30 40
    Output:
        2
    
    Input:
        3 7
        5 10 15
    Output:
        -1''',
                'order': 2,
                'points': 10,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and find element
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, target, i;
    scanf("%d %d", &n, &target);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int index = -1;
    for (i = 0; i < n; i++) {
        if (arr[i] == target) {
            index = i;
            break;
        }
    }
    printf("%d\\n", index);
    return 0;
}''',
                'solution_explanation': '''This solution performs a linear search to find the target element in the array. It reads the array size and target value, then reads all array elements. It iterates through the array comparing each element with the target. When found, it stores the index and breaks. If not found, index remains -1.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('4 30\\n10 20 30 40', '2', False, 0.5),
                    ('3 7\\n5 10 15', '-1', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'Bubble Sort (C)',
                'description': '''Read an array and output it sorted in ascending order using bubble sort.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        5
        64 34 25 12 22
    Output:
        12 22 25 34 64
    
    Input:
        5
        5 1 4 2 8
    Output:
        1 2 4 5 8''',
                'order': 3,
                'points': 25,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and bubble sort
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i, j;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    for (i = 0; i < n - 1; i++) {
        for (j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
    for (i = 0; i < n; i++) {
        printf("%d", arr[i]);
        if (i < n - 1) printf(" ");
    }
    printf("\\n");
    return 0;
}''',
                'solution_explanation': '''This solution implements bubble sort algorithm. The outer loop runs n-1 times, and the inner loop compares adjacent elements, swapping them if they're in wrong order. After each pass, the largest unsorted element "bubbles up" to its correct position. The time complexity is O(n²) and space complexity is O(1).''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('5\\n64 34 25 12 22', '12 22 25 34 64', False, 0.5),
                    ('5\\n5 1 4 2 8', '1 2 4 5 8', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'Binary Search (C)',
                'description': '''Implement binary search on a sorted array.
Output the index of target if found, -1 otherwise.

Input format:
    First line: number of elements and target (space-separated)
    Second line: space-separated sorted integers

Example:
    Input:
        6 9
        -1 0 3 5 9 12
    Output:
        4
    
    Input:
        6 2
        -1 0 3 5 9 12
    Output:
        -1''',
                'order': 4,
                'points': 25,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and perform binary search
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, target, i;
    scanf("%d %d", &n, &target);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int left = 0, right = n - 1;
    int result = -1;
    while (left <= right) {
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) {
            result = mid;
            break;
        } else if (arr[mid] < target) {
            left = mid + 1;
        } else {
            right = mid - 1;
        }
    }
    printf("%d\\n", result);
    return 0;
}''',
                'solution_explanation': '''This solution implements binary search algorithm on a sorted array. It maintains left and right pointers and calculates the middle index. If the middle element equals the target, it returns the index. If the target is greater, it searches the right half; otherwise, it searches the left half. Time complexity is O(log n).''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('6 9\\n-1 0 3 5 9 12', '4', False, 0.5),
                    ('6 2\\n-1 0 3 5 9 12', '-1', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'String Compare (C)',
                'description': '''Read two strings and compare them without using strcmp().
Output 0 if equal, negative if str1 < str2, positive if str1 > str2.

Input format:
    First line: first string
    Second line: second string

Example:
    Input:
        hello
        hello
    Output:
        0
    
    Input:
        abc
        abd
    Output:
        -1''',
                'order': 5,
                'points': 20,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and compare strings
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    char str1[1000], str2[1000];
    scanf("%s", str1);
    scanf("%s", str2);
    int i = 0;
    while (str1[i] != '\\0' && str2[i] != '\\0') {
        if (str1[i] != str2[i]) {
            printf("%d\\n", str1[i] - str2[i]);
            return 0;
        }
        i++;
    }
    printf("%d\\n", str1[i] - str2[i]);
    return 0;
}''',
                'solution_explanation': '''This solution compares two strings character by character without using strcmp(). It iterates through both strings simultaneously, comparing corresponding characters. If a difference is found, it returns the difference of their ASCII values. If the loop completes, it compares the characters at position i (which will be '\\0' for equal-length equal strings).''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('hello\\nhello', '0', False, 0.5),
                    ('abc\\nabd', '-1', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'Maximum Subarray (C)',
                'description': '''Find the contiguous subarray with the largest sum and output that sum.

Input format:
    First line: number of elements
    Second line: space-separated integers

Example:
    Input:
        9
        -2 1 -3 4 -1 2 1 -5 4
    Output:
        6
    
    Input:
        5
        5 4 -1 7 8
    Output:
        23''',
                'order': 6,
                'points': 30,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and find maximum subarray sum
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int n, i;
    scanf("%d", &n);
    int arr[n];
    for (i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    int max_sum = arr[0];
    int current_sum = arr[0];
    for (i = 1; i < n; i++) {
        current_sum = (current_sum + arr[i] > arr[i]) ? current_sum + arr[i] : arr[i];
        max_sum = (current_sum > max_sum) ? current_sum : max_sum;
    }
    printf("%d\\n", max_sum);
    return 0;
}''',
                'solution_explanation': '''This solution implements Kadane's algorithm to find the maximum subarray sum in O(n) time. It maintains two variables: current_sum (maximum sum ending at current position) and max_sum (overall maximum). For each element, it decides whether to extend the existing subarray or start a new one, then updates the maximum if needed.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('9\\n-2 1 -3 4 -1 2 1 -5 4', '6', False, 0.5),
                    ('5\\n5 4 -1 7 8', '23', True, 0.5)
                ]
            },
            {
                'quiz': quizzes[3],
                'title': 'Palindrome Number (C)',
                'description': '''Check if an integer is a palindrome without converting to string.
Output 1 for palindrome, 0 otherwise.

Example:
    Input:
        121
    Output:
        1
    
    Input:
        -121
    Output:
        0''',
                'order': 7,
                'points': 25,
                'starter_code': '''#include <stdio.h>

int main() {
    // Read input and check palindrome
    // Your code here
    return 0;
}''',
                'solution': '''#include <stdio.h>

int main() {
    int x;
    scanf("%d", &x);
    if (x < 0) {
        printf("0\\n");
        return 0;
    }
    int original = x;
    int reversed = 0;
    while (x > 0) {
        reversed = reversed * 10 + x % 10;
        x /= 10;
    }
    printf("%d\\n", original == reversed ? 1 : 0);
    return 0;
}''',
                'solution_explanation': '''This solution checks if a number is a palindrome by reversing it mathematically without string conversion. Negative numbers are not palindromes. It extracts digits from right to left using modulo and integer division, building the reversed number. Finally, it compares the reversed number with the original.''',
                'language': 'c',
                'created_by': '3',
                'test_cases': [
                    ('121', '1', False, 0.5),
                    ('-121', '0', True, 0.5)
                ]
            },
        ]

        grouped = {}
        for index, q_data in enumerate(questions_data, start=1):
            title = canonical_problem_title(q_data['title'])
            key = title.lower()
            language = (q_data.get('language') or 'python').lower()

            if key not in grouped:
                grouped[key] = {
                    'slug': slugify_problem(title, index),
                    'title': title,
                    'description': q_data['description'],
                    'difficulty': q_data.get('difficulty', 'easy'),
                    'order': q_data.get('order', index),
                    'points': q_data.get('points', 10),
                    'created_by': int(q_data.get('created_by') or teachers[0].id),
                    'test_cases': q_data.get('test_cases', []),
                    'quiz_links': [],
                    'variants': {},
                }

            problem_data = grouped[key]
            problem_data['variants'][language] = {
                'starter_code': q_data.get('starter_code', ''),
                'solution': q_data.get('solution', ''),
                'solution_explanation': q_data.get('solution_explanation', ''),
            }

            if language == 'python' or not problem_data['test_cases']:
                problem_data['test_cases'] = q_data.get('test_cases', [])

            if not any(link['quiz'].id == q_data['quiz'].id for link in problem_data['quiz_links']):
                problem_data['quiz_links'].append({
                    'quiz': q_data['quiz'],
                    'order': q_data.get('order', index),
                    'points': q_data.get('points', 10),
                })

        problems_data = list(grouped.values())

        for p_data in problems_data:
            problem = Problem(
                slug=p_data['slug'],
                title=p_data['title'],
                description=p_data['description'],
                difficulty=p_data.get('difficulty', 'easy'),
                points=p_data.get('points', 10),
                order=p_data.get('order', 1),
                created_by=p_data.get('created_by'),
            )
            db.session.add(problem)
            db.session.flush()

            for link in p_data['quiz_links']:
                db.session.add(QuizProblem(
                    quiz_id=link['quiz'].id,
                    problem_id=problem.id,
                    order=link.get('order', 1),
                    points=link.get('points', p_data.get('points', 10)),
                ))

            for input_data, expected, is_hidden, weight in p_data['test_cases']:
                db.session.add(TestCase(
                    problem_id=problem.id,
                    input=input_data,
                    expected_output=expected,
                    is_hidden=is_hidden,
                    weight=weight,
                ))

            for language, variant_data in p_data['variants'].items():
                db.session.add(Question(
                    problem_id=problem.id,
                    programming_language=language,
                    starter_code=variant_data.get('starter_code', ''),
                    solution=variant_data.get('solution', ''),
                    solution_explanation=variant_data.get('solution_explanation', ''),
                ))

        db.session.commit()
        print(f"✓ {len(problems_data)} problems created with {Question.query.count()} language variants")
        
        # ============================================
        # Verification
        # ============================================
        print("\n" + "="*70)
        print("Verifying data...")
        
        total_problems = Problem.query.count()
        total_variants = Question.query.count()
        total_quiz_problems = QuizProblem.query.count()

        print(f"   - Problems: {total_problems}")
        print(f"   - Language variants: {total_variants}")
        print(f"   - QuizProblem associations: {total_quiz_problems}")

        for quiz in quizzes:
            count = QuizProblem.query.filter_by(quiz_id=quiz.id).count()
            print(f"   - {quiz.title}: {count} problems")
        
        # ============================================
        # Completion
        # ============================================
        print("\n" + "="*70)
        print("Database seeded successfully!")
        print("="*70)
        print("\nSummary:")
        print(f"   • Users: 1 admin + {len(teachers)} teachers + {len(students)} students")
        print(f"   • Classrooms: {len(classrooms)}")
        print(f"   • Enrollments: {enrollment_count}")
        print(f"   • Quizzes: {len(quizzes)}")
        print(f"   • Quiz Assignments: {len(assignments)}")
        print(f"   - Problems: {total_problems}")
        print(f"   - Language variants: {total_variants}")
        print(f"   - QuizProblem associations: {total_quiz_problems}")
        print(f"\n Login credentials (all passwords: admin123):")
        print(f"   • admin / admin123")
        print(f"   • teacher1-3 / admin123")
        print(f"   • student1-8 / admin123")
        print()
        
    except Exception as e:
        db.session.rollback()
        print(f"\n Error seeding data: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Database initialization script (Fixed for MySQL foreign keys)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python init_db.py                # Create tables only
  python init_db.py --seed         # Create tables and add test data
  python init_db.py --drop --seed  # Drop all, recreate, and seed
        '''
    )
    parser.add_argument('--drop', action='store_true', 
                       help='Drop all tables before creating')
    parser.add_argument('--seed', action='store_true', 
                       help='Seed database with test data')
    parser.add_argument('--force', action='store_true',
                   help='Force operation without confirmation (for Docker)')
    args = parser.parse_args()
    
    print("\n" + "="*70)
    print("CodeRunner Database Initialization ")
    print("="*70)

    
    # Create application
    app = create_app()
    
    with app.app_context():
       
      flask_env = os.environ.get('FLASK_ENV', 'production')
      is_production = flask_env == 'production'
        
      if is_production:
          print(f"⚠ Running in PRODUCTION mode")
      else:
          print(f"ℹ Running in {flask_env.upper()} mode")
        
      # Drop tables if requested (NO CONFIRMATION)
      if args.drop:
          tables_exist = check_tables_exist()
          
          if tables_exist:
              print(f"\n⚠ WARNING: Dropping existing tables!")
          
          drop_all()
      
      # Create tables
      create_all()
      
      # Seed data if requested
      if args.seed:
          seed_data()
      
      print("\n" + "="*70)
      print("Database initialization completed!")
      print("="*70)
      print()


if __name__ == '__main__':
    main()
