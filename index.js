var app = require('express').createServer();
var xhr = require('./xhr.js');

app.set('view options', {
    layout: false
});

var readFeed = function(feed) {
    xhr.get('http://www.eksisozluk.com/show.asp?t='+feed, 
            function(responseText, response) {
                console.log(responseText);
            });
}

app.get('/', function(req, res) {
    console.log('main page requested');

    res.render('index.ejs', {});
});

app.get('/feed/', function(req, res){
    console.log('Feed requested: ' + req.query.t);

    readFeed(req.query.t);

    //res.render('rssfeed_tpl.ejs', {});
});

app.listen(3000);

readFeed('haci+murat');
