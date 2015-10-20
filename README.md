App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions

If you want to use this code on your app engine application follow this instructions:

1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

If you want to use the live API follow this instructions:

1. Access this [link][7]
1. Click on the "Conference API" button to explore the avalible methods

## Files

1. app.yaml: the URL config file, it defines what part of the application wil handle each URL request
1. cron.yaml: defines the application's cron jobs
1. index.yaml: define the DB's indexes needed for the application's queries
1. main.py: defines the URL handlers involved with the cron jobs and the task queues
1. models.py: it has the classes and methods responsables for the application's data structure (data base and API messages)
1. conference.py: it defines the API class and methods

## Tasks
INCLUIR UMA EXPLICACAO MELHOR DE COMO EU FIZ A PARTE OPERACIONAL DO MODEL DO SESSION DO SPEAKER (FALAR DOS DATATYPES DE CADA PROPRIEDADE)
1. Task 1: 
   I've added the Session and SessionForm (with the corresponding fields) in the models.py file as requested, I also implemented a entity for the Speaker (SpeakerForm and SpeakerForms too) in order to open the possibility to query for sessions and/or speakers based on relevant information about the speaker (like query for sessions where the speaker works for google or find speakers especialized on app engine and python).
   On the session model I used the string data type for the name, highlights, speaker and typeOfSession because those information could be easily stored and queried as strings, also the speaker property is repeated because is possible to have a session with more than one speaker, for the duration and start properties I've used the TimeProperty as the data type because those are measures of time and this type make it possible to query and compare these properties inside the 0-24 hours time range, and finaly for the date property I used the DateProperty as data type because it is the appropriate one to store and query dates. For the speaker entity I've chosen the StringProperty for all the properties (name, biography, specialty and company) because those information could be easily stored and queried as strings, also the specialty property is repeated because is possible to have a speaker with more than one specialty.
   To make the integration of session and speaker possible, without modifying the session properties, I used the speaker's name as sort of primary key for this entity. I know that this property is not suited for this role due to the strong possibility of two speakers having the same name, but I chose it in order to attend to the project specifications.
   The speakers are created in two diferent ways, the first is by the "createSpeaker" API method where the user can input relevant informations (name, company, biography and specialty) about the new speaker, and the second is by creating a new session and informing a speaker's name that is not on the applications data base, in this case the application will create a default speaker with the inputted name. I've chosen this hybrid way of dealing with the speaker entity in order to give the user the possibility to choose if he wants or not the detailed speaker information.
1. Task 3:
   The two aditional queries I've proposed were thought to take advantage of the speaker's entity potential, the first query is to look for sessions in a conference based on the speaker's working company (implemented on the getConferenceSessionsByCompany API method), in this method I look for all the sessions on the conference and all the speakers that work for the inputted company, than I select the sessions where at least one of the selected speakers is listed, the second query is to look for sessions based on the speaker specialty (implemented on the getConferenceSessionsBySpeakerSpecialty API method), it works like the first one but instead I filter the speaker by specialty not company.
   The proposed query is problematic because the ndb database have a limitation where you can't have inequality filter on more than one different property, and the proposed query demand the property "typeOfSession" to be different of "workshop" and the "start" to be less than "19:00". 
   To overcome this limitation I've made a function (_getGenericQuery) that separate the equality and the inequality filters, than it performs a query based on the equality filters, and using other functions, it filters the query's result based on the inequality filters, this way you can have as many inequality filters as you want because they wont be used in the ndb query, they will be used to process the query result. Since this method breaks the query in two it is slower than a regular query so I've tryed to use async operations to minimize this effect (since it isn't covered on the course I've made it based on my personal research and I will really appreciate if you could give me your professional feedback on what I did on those async ops, tks!).
   Other relevant aspect about the _getGenericQuery function is that it is generic and can be used to make any kind of query on any entity, to prove it I've implemented the querySessions and querySpeaker API methods, where you can query for sessions and speakers respectively using any criterias you want.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[7]: https://ud-calixto.appspot.com/_ah/api/explorer
