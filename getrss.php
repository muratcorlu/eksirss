<?php
$word = strtolower($word);
$file = './cache/'. md5($word) . '.xml';
Header('Content-Type: application/rss+xml;charset=utf-8');

function addUrl($el) {
	$link = pq($el)->attr('href');
	if(stripos($link, 'http') === false){
		pq($el)->attr('href', 'http://sozluk.sourtimes.org/'.$link);
	}
}

function success($browser) {
	global $doc, $word;

	$es = phpQuery::newDocumentHTML($browser);
	phpQuery::selectDocument($es);
	
	$title = str_replace('*', '', pq('h1.title')->text());
	//TODO: Yonlendirmede i parametresi gitmediginden son sayfa degil ilk sayfa geliyor
	//if($title!=$word){
	//	phpQuery::browserGet('http://sozluk.sourtimes.org/show.asp?t='.$title.'&i=900090020', 'success');
	//}else{
		pq('script, div.aul table')->remove();
	
		$doc['channel > title']->text($title);
		$doc['channel > description']->text(pq('h1.title')->text() . ' on Ekşi Sözlük');
		$doc['channel > lastBuildDate']->text(date(DATE_RFC822));

		$LIs = pq('li');
		foreach($LIs as $li) {
			$title = str_replace(array('(',')'), '', pq($li)->find('div.aul')->text());
			pq($li)->find('div.aul')->remove();
			pq($li)->find('a')->each('addUrl');
			$id = str_replace('d','',pq($li)->attr('id'));
			if (strlen($id)>0 ) {
				$link = 'http://sozluk.sourtimes.org/show.asp?id='.$id;
				$doc['channel']->prepend('<item><title>'.$title.'</title><description>'.htmlspecialchars(pq($li)->html()).'</description><link>'.$link.'</link></item>');
			}
		}
	//}
}


if(file_exists($file) && (time() - filemtime($file) < 3 * 60 * 60) ) {
	$doc = file_get_contents($file);
}else{
	$doc = phpQuery::newDocumentFileXML('rssfeed_tpl.xml');
	$doc['item']->remove();

	phpQuery::ajaxAllowHost('sozluk.sourtimes.org');
	phpQuery::browserGet('http://sozluk.sourtimes.org/show.asp?t='.$word.'&i=900090020', 'success');

	file_put_contents($file, ''.$doc);
}

print $doc;
