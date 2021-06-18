"""Mock data for testing"""

MOCK_REPOSITORY = {
   "url":"https://localhost:8080/repositories",
   "id":"repo_123"
}
MOCK_POST_REPOSITORY = {
   "access_token":"xxxxxxxxxxxxxx",
   "id":"repository_123"
}

MOCK_BUILD_INFO = {
   "images":[
      {
         "name":"akash7778/broker:0.0.1",
         "location":"./Dockerfile"
      },
      {
         "name":"akash7778/broker:0.0.1",
         "location":"./Dockerfile"
      }
   ],
   "head_commit":{
      "branch":"development",
      "commit_sha":"930fd5"
   },
   "status":"UNKNOWN",
   "started_at":"2021-06-11T17:32:28Z",
   "finished_at":"2021-06-11T17:32:28Z"
}

MOCK_SUBSCRIPTION = {
   "subscription_id":"subscription-xyz"
}
MOCK_SUBSCRIPTION_INFO = {
   "callback_url":"https://ec2-54-203-145-132.compute-1.amazonaws.com/update",
   "repository_id":"respository123",
   "build_id":"build_123",
   "build_type":"production",
   "state":"Active",
   "updated_at":"2021-06-11T17:32:28+00:00"
}
