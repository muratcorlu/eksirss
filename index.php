<?php

require "phpQuery.php";

//phpQuery::$debug = 1;

$word = urlencode($_GET['t']);

if(strlen(trim($word))==0) {
	include 'main.html';
}else{
	include 'getrss.php';
}
