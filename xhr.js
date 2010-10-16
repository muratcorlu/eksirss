var http = require('http'),
    url = require('url');

exports.get = function(fullUrl, callback) {
    var urlObj = url.parse(fullUrl, true);
    console.log(urlObj);

    var request = http.createClient(80, urlObj.host)
                      .request('GET', 
                                urlObj.pathname+urlObj.search, 
                                {'host': urlObj.host});
    request.end();

    request.on('response', function(response) {
        var body = '';
        console.log('Status: '+response.statusCode);
        response.setEncoding('utf8');

        response.on('data', function(chunk) {
            body += chunk;
        });

        response.on('end', function() {
            console.log('Bitti');
            callback.call(this, body, response);
        });
    });
}
