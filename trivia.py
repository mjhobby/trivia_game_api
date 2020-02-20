from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
import json
import os
from random import shuffle
import requests
import uuid
from xml.etree import ElementTree
from zeep import Client


app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(os.path.join(basedir, 'trivia.sqlite'))
db = SQLAlchemy(app)
ma = Marshmallow(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    email = db.Column(db.String(120), unique=True)
    score = db.Column(db.Integer, default=0)
    questions = db.Column(db.Integer, default=0)
    correct_answers = db.Column(db.Integer, default=0)

    def __init__(self, username, email):
        self.username = username
        self.email = email


class UserSchema(ma.Schema):
    class Meta:
        fields = ('username', 'email', 'score', 'questions', 'correct_answers')


user_schema = UserSchema()
users_schema = UserSchema(many=True)

def generate_uuid():
    return str(uuid.uuid4())


class TriviaQuestion(db.Model):
    secret_key = db.Column(db.String, primary_key=True, unique=True, nullable=False, default=generate_uuid())
    question = db.Column(db.String(256), nullable=False)
    question_value = db.Column(db.Integer, default=0)
    answer_options = db.Column(db.String(256), nullable=False)
    correct_answer = db.Column(db.String(64), nullable=False)


class TriviaQuestionSchema(ma.Schema):
    class Meta:
        fields = ('question', 'answer_options', 'secret_key')


trivia_question_schema = TriviaQuestionSchema()


@app.route("/user", methods=["POST"])
def add_user():
    """Endpoint for adding a new user"""
    username = request.json['username']
    email = request.json['email']

    user = User(username, email)

    db.session.add(user)
    db.session.commit()
    return user_schema.jsonify(user)

@app.route("/user/<id>", methods=["GET"])
def get_user(id):
    """Endpoint to retrieve a specific user"""
    user = User.query.get(id)
    return user_schema.jsonify(user)

@app.route("/user/<id>", methods=["PUT"])
def update_user(id):
    user = User.query.get(id)
    username = request.json['username']
    email = request.json['email']

    user.email = email
    user.username = username

    db.session.commit()
    return user_schema.jsonify(user)

@app.route("/user/<id>", methods=["DELETE"])
def delete_user(id):
    user = User.query.get(id)
    db.session.delete(user)
    db.session.commit()

    return user_schema.jsonify(user)

@app.route("/question", methods=["GET"])
def get_question():
    # Get random difficulty
    response = requests.get('http://roll.diceapi.com/json/d3')
    die_roll = json.loads(response.text)
    difficulty_mappings = {
        1: 'easy',
        2: 'medium',
        3: 'hard'
    }
    roll_value = die_roll['dice'][0]['value']
    difficulty = difficulty_mappings[roll_value]
    value = roll_value * 100
    
    # Get random Category ID
    response = requests.get('http://roll.diceapi.com/json/d24')
    category_id = int(json.loads(response.text)['dice'][0]['value']) + 8

    # Get Random question of difficulty and category
    params = {
        'amount': '1',
        'category': str(category_id),
        'difficulty': difficulty
    }
    response = requests.get(url='https://opentdb.com/api.php', params=params)
    response_result = json.loads(response.text)['results'][0]
    
    question = response_result['question']
    answer = response_result['correct_answer']
    options = response_result['incorrect_answers']
    options.append(answer)
    shuffle(options)

    trivia_question = TriviaQuestion(question=question, answer_options=','.join(options), correct_answer=answer, question_value=value)
    db.session.add(trivia_question)
    db.session.commit()
    return trivia_question_schema.jsonify(trivia_question)

@app.route("/submit_answer", methods=["POST"])
def submit_answer():
    request_data = {
        'answer': request.json['answer'],
        'username': request.json['username'],
        'questionSecretKey': request.json['secret_key']
    }
    client = Client(wsdl=os.path.join(basedir, "trivia_answer.wsdl"))
    response = client.service.submitAnswer(**request_data)

    formatted_response = {
        'result': response['result'],
        'username': response['username'],
        'userScore': response['userScore'],
        'pctCorrect': response['pctCorrect']
    }
    return json.dumps(formatted_response)


@app.route("/answer", methods=["POST"])
def answer():
    request_data = ElementTree.fromstring(request.data)
    request_body = request_data.getchildren()[0].find('submitAnswer')
    
    answer = request_body.find('answer').text
    username = request_body.find('username').text
    secret_key = request_body.find('questionSecretKey').text
    user = db.session.query(User).filter_by(username=username)[0]

    trivia_question = TriviaQuestion.query.get(secret_key)
    user.questions = user.questions + 1

    result = 'Sorry. That\'s incorrect! The correct answer was {}.'.format(trivia_question.correct_answer)
    if trivia_question.correct_answer == answer:
        result = 'That\'s correct!'
        user.correct_answers = user.correct_answers + 1
        user.score = user.score + trivia_question.question_value
    pct_corr = round((user.correct_answers/user.questions) * 100)

    db.session.delete(trivia_question)
    db.session.commit()

    response = '<?xml version=\'1.0\' encoding=\'utf8\'?>\n<ns0:Envelope xmlns:ns0="http://schemas.xmlsoap.org/soap/envelope/"><ns0:Body><submitAnswer><result>{result}</result><username>{username}</username><userScore>{score}</userScore><pctCorrect>{pct_corr}%</pctCorrect></submitAnswer></ns0:Body></ns0:Envelope>'.format(result=result, username=username, score=user.score, pct_corr=pct_corr)
    return response


if __name__ == '__main__':
    app.run(debug=True)
