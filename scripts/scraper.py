# -*- coding:Utf-8 -*-

#  Dieren Theater - lachambre.be to json sausage machine
#  Copyright (C) 2011  Laurent Peuch <cortex@worlddomination.be>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
from os.path import exists
from urllib import urlopen, quote
from BeautifulSoup import BeautifulSoup
from lxml import etree

from deputies.models import Deputy, Party, CommissionMembership, Document, Question, Analysis, Commission, WrittenQuestion

LACHAMBRE_PREFIX="http://www.lachambre.be/kvvcr/"

def clean_text(text):
    return re.sub("(\r|\t|\n| )+", " ", text).replace("&#13; ", "").replace("&#13;", "").strip()

def hammer_time(function):
    "decorator to retry to download a page because La Chambre website sucks"
    def wrap(*args, **kwargs):
        reset = False
        for i in xrange(4):
            try:
                return function(*args, reset=reset, **kwargs)
            except (IndexError, AttributeError, TypeError), e:
                print e
                reset = True
        print "WARNING, function keeps failling", function, args, kwargs
    return wrap

def lame_url(url):
    # convert super lame urls of lachambre.be into something uzable
    return quote(url.encode("iso-8859-1"), safe="%/:=&?~#+!$,;'@()*[]")

def get_or_create(klass, _id=None, **kwargs):
    if _id is None:
        object = klass.objects.filter(**kwargs)
    else:
        object = klass.objects.filter(**{_id : kwargs[_id]})
    if object:
        return object[0]
    else:
        print "add new", klass.__name__, kwargs
        return klass.objects.create(**kwargs)

def read_or_dl(url, name, reset=False):
    print "parsing", url
    if not reset and exists('dump/%s' % name):
        text = open('dump/%s' % name).read()
    else:
        text = urlopen(url).read()
        open('dump/%s' % name, "w").write(text)
    soup = BeautifulSoup(text)
    if soup.title.text == "404 Not Found":
        raise IndexError
    return soup

def lxml_read_or_dl(url, name, reset=False):
    print "parsing", url
    if not reset and exists('dump/%s' % name):
        text = open('dump/%s' % name)
    else:
        text = urlopen(url)
        open('dump/%s' % name, "w").write(text)
    soup = etree.parse(text, etree.HTMLParser())
    return soup

def table2dic(table):
    dico = {}
    for x, y in zip(table[::2], table[1::2]):
        dico[x.text] = y.text if y.a is None else y.a
    return dico

def clean():
    print "cleaning db"
    map(lambda x: x.objects.all().delete(), (Deputy, Party, CommissionMembership, Document, Question, Analysis, Commission, WrittenQuestion))

@hammer_time
def deputies_list(reset=False):
    soup = read_or_dl("http://www.lachambre.be/kvvcr/showpage.cfm?section=/depute&language=fr&rightmenu=right_depute&cfm=/site/wwwcfm/depute/cvlist.cfm", "deputies", reset)

    for dep in soup('table')[4]('tr'):
        items = dep('td')
        full_name = re.sub('  +', ' ', items[0].a.text).strip()
        url = items[0].a['href']
        party = get_or_create(Party, name=items[1].a.text, url=dict(items[1].a.attrs)['href'])
        email = items[2].a.text
        website = items[3].a['href'] if items[3].a else None
        # yes, one deputies key contains a O instead of an 0, I'm not joking
        lachambre_id = re.search('key=([0-9O]+)', url).groups()[0]
        Deputy.objects.create(full_name=full_name,
                              party=party,
                              url=url,
                              websites=[website] if website else [],
                              lachambre_id=lachambre_id,
                              emails=[email])
        print 'adding new deputy', lachambre_id, full_name, party, email, website if website else ''

def each_deputies():
    for index, deputy in enumerate(list(Deputy.objects.all())):
        print index, deputy.full_name
        parse_deputy(deputy)

@hammer_time
def parse_deputy(deputy, reset=False):
    soup = read_or_dl(LACHAMBRE_PREFIX + deputy.url, deputy.full_name, reset)
    deputy.language = soup.i.parent.text.split(":")[1] if soup.i else None
    deputy.cv = re.sub('  +', ' ', soup('table')[5].p.text)
    if deputy.cv.encode("Utf-8").startswith("Députée"):
        deputy.sex = "F"
    elif deputy.cv.encode("Utf-8").startswith("Député"):
        deputy.sex = "M"
    else:
        deputy.sex = None

    # stupid special case
    if deputy.full_name == "Fernandez Fernandez Julie":
        deputy.first_name = "Julie"
        deputy.last_name = "Fernandez Fernandez"
    elif deputy.full_name == "Dedecker Jean Marie":
        deputy.first_name = "Jean Marie"
        deputy.last_name = "Dedecker"
    # here we guess the first and last name, for that we compare
    # deputy.full_name that is in the form of "de Donnea
    # François-Xavier" and the name of the deputy page which is in the
    # form of "François-Xavier de Donnea"
    elif len(deputy.full_name.split(" ")) > 2:
        it = 0
        while it < len(deputy.full_name.split(" ")):
            if soup.h2.text.split(" ")[it] != deputy.full_name.split(" ")[-(it + 1)]:
                break
            it += 1
            print it, soup.h2.text.split(" ")[it], deputy.full_name.split(" ")[-(it + 1)]
        if not it:
            raise Exception
        deputy.first_name = " ".join(soup.h2.text.split(" ")[:it]).strip()
        deputy.last_name = " ".join(soup.h2.text.split(" ")[it:]).strip()
        print [deputy.first_name], [deputy.last_name]
    else:
        # if there is only 2 words just split this in 2
        deputy.first_name = deputy.full_name.split(" ")[1].strip()
        deputy.last_name = deputy.full_name.split(" ")[0].strip()
        print [deputy.first_name], [deputy.last_name]

    # here we will walk in a list of h4 .. h5 .. div+ .. h5 .. div+
    # look at the bottom of each deputies' page
    membership = soup.find('td', rowspan="1")
    item = membership.h4
    role = None
    while item.nextSibling:
        if hasattr(item, 'tag'):
            if item.name == 'h5':
                role = item.text[6:-1]
            elif item.name == 'div':
                print "linking deputy to commission", item.a.text
                commission = get_or_create(Commission, lachambre_id=int(re.search("com=(\d+)", item.a["href"]).groups()[0]))
                deputy.commissions.append(CommissionMembership.objects.create(commission=commission, name=item.a.text, role=role, url=item.a['href']))
        item = item.nextSibling

    deputy_documents(soup, deputy)
    deputy.save()

@hammer_time
def get_deputy_documents(url, deputy, role, type=None, reset=False):
    print "working on %s %sdocuments" % (role, type + " " if type else '') #, LACHAMBRE_PREFIX + lame_url(urls[index])
    soupsoup = read_or_dl(LACHAMBRE_PREFIX + lame_url(url), '%s %s %s' % (deputy.full_name, type if type else '', role), reset)
    setattr(deputy, "documents_%s%s_url" % (role, type + "_" if type else ''), url)
    setattr(deputy, "documents_%s%s_list" % (role, type + "_" if type else ''), [])
    for i in soupsoup('table')[3]('tr', valign="top"):
        print "add", type if type else '', role, i.tr('td')[1].text
        dico = table2dic(i.table('td'))
        print dico
        getattr(deputy, "documents_%s%s_list" % (role, type + "_" if type else '')).\
                append(get_or_create(Document, _id="lachambre_id",
                                     lachambre_id=re.search("dossierID=(\d+)", i.a["href"]).groups()[0],
                                     url=i.a['href'],
                                     title=dico["Titre :"],
                                     status_chambre=dico.get("Chambre FR :"),
                                     status_senat=dico.get("Sénat FR :"),
                                     date=dico.get("Date :"),
                                     eurovoc_main_descriptor=dico.get("Desc. Eurovoc principal :"),
                                     eurovoc_descriptors=map(lambda x: x.strip(), dico.get("Descripteurs Eurovoc :", "").split('|')),
                                     keywords=map(lambda x: x.strip(), dico.get("Mots-clés libres :", "").split('|'))))

@hammer_time
def get_deputy_written_questions(url, deputy, reset=False):
    soupsoup = read_or_dl(LACHAMBRE_PREFIX + lame_url(url), deputy.full_name + " written questions", reset)
    deputy.questions_written_url = url
    deputy.questions_written_list = []
    for i in soupsoup('table')[3]('tr', valign="top"):
        print "add", type, i.tr('td')[1].text.strip()
        dico = table2dic(i.table('td'))
        print dico
        deputy.questions_written_list.\
                append(get_or_create(WrittenQuestion,
                                     _id="lachambre_id",
                                     title=dico["Titre"],
                                     departement=dico.get(u"Département"),
                                     lachambre_id=re.search("dossierID=([0-9A-Za-z-]+)", i.a["href"]).groups()[0],
                                     deposition_date=dico.get(u"Date de dépôt"),
                                     delay_date=dico.get(u"Date de délai"),
                                     eurovoc_descriptors=map(lambda x: x.strip(), dico.get("Descripteurs Eurovoc", "").split('|')),
                                     keywords=map(lambda x: x.strip(), dico.get(u"Mots-clés libres", "").split("|")),
                                     url=i.a['href']))

@hammer_time
def get_deputy_questions(url, deputy, type, reset=False):
    soupsoup = read_or_dl(LACHAMBRE_PREFIX + lame_url(url), '%s %s' % (deputy.full_name, type), reset)
    setattr(deputy, "questions_%s_url" % type, url)
    setattr(deputy, "questions_%s_list" % type, [])
    for i in soupsoup('table')[3]('tr', valign="top"):
        print "add", type, i.tr('td')[1].text.strip()
        dico = table2dic(i.table('td'))
        print dico
        getattr(deputy, "questions_%s_list" % type).\
                append(get_or_create(Question,
                                     _id="lachambre_id",
                                     title=dico["Titre"],
                                     lachambre_id=re.search("dossierID=([0-9A-Za-z-]+)", i.a["href"]).groups()[0],
                                     reunion_type=dico.get(u"Réunion"),
                                     reunion_date=dico.get("Date discussion"),
                                     session_id=dico.get("Session"),
                                     pdf_url=dico.get(u"Compte rendu intégral", {"href": None})["href"],
                                     eurovoc_descriptors=map(lambda x: x.strip(), dico.get("Descripteurs Eurovoc", "").split('|')),
                                     keywords=map(lambda x: x.strip(), dico.get(u"Mots-clés libres", "").split("|")),
                                     url=i.a['href'],
                                     type=type))

@hammer_time
def get_deputy_analysis(url, deputy, type, reset=False):
    soupsoup = read_or_dl(LACHAMBRE_PREFIX + lame_url(url), '%s %s' % (deputy.full_name, type), reset)
    setattr(deputy, "analysis_%s_url" % type, url)
    setattr(deputy, "analysis_%s_list" % type, [])
    for i in soupsoup('table')[3]('tr', valign="top"):
        print "add", type, i.tr('td')[1].text.strip()
        dico = table2dic(i.table('td'))
        print dico
        getattr(deputy, "analysis_%s_list" % type).\
                append(get_or_create(Analysis,
                                     _id="lachambre_id",
                                     lachambre_id=re.search("dossierID=([0-9A-Za-z-]+)", i.a["href"]).groups()[0],
                                     title=dico["Titre"],
                                     descriptor=dico["Descripteurs"],
                                     url=i.a['href'],
                                     type=type))

def deputy_documents(soup, deputy):
    # here we are in the grey black box
    urls = map(lambda x: x['href'], soup('div', **{'class': 'linklist_1'})[1]('a'))

    get_deputy_documents(urls[0], deputy, "author", "principal")
    get_deputy_documents(urls[1], deputy, "signator", "principal")
    get_deputy_documents(urls[2], deputy, "author", "next")
    get_deputy_documents(urls[3], deputy, "signator", "next")
    get_deputy_documents(urls[4], deputy, "rapporter")
    get_deputy_written_questions(urls[5], deputy)
    # no one seems to do any interpellations nor motions or maybe the website is just broken
    get_deputy_questions(urls[8], deputy, "oral_plenary")
    get_deputy_questions(urls[9], deputy, "oral_commission")
    get_deputy_analysis(urls[10], deputy, "legislatif_work")
    get_deputy_analysis(urls[11], deputy, "parlimentary_control")
    get_deputy_analysis(urls[12], deputy, "divers")

def deputies():
    deputies_list()
    each_deputies()

def document_to_dico(table):
    dico = {}
    sub_section = None
    for i in table:
        if i == u"\n":
            continue
        if i.td.text in ("&#13;", "&nbsp;", "&#160;"):
            continue
        if i.td.b:
            sub_section = clean_text(i.td.b.text)
            if dico.get(sub_section):
                raise Exception("'%s' is already use as a key for '%s'" % (sub_section, dico[sub_section]))
            dico[sub_section] = {}
            dico[sub_section]["head"] = i('td')[1]
        elif i.td.img:
            key = clean_text(i.td.text)
            # we can have a list on joined documents
            if str(key) == 'Document(s) joint(s)/li&#233;(s)':
                if not dico[sub_section].get(key):
                    dico[sub_section][key] = []
                dico[sub_section][key].append(i('td')[1])
            else:
                if dico[sub_section].get(key):
                    raise Exception("'%s' is already use as a key in the sub_section '%s' for '%s'" % (key, sub_section, dico[sub_section][key]))
                dico[sub_section][key] = i('td')[1]
        else:
            key = clean_text(i.td.text)
            # we can get severals Moniter erratum
            if str(key) == 'Moniteur erratum':
                if not dico.get(key):
                    dico[key] = []
                dico[key].append(i('td')[1])
            else:
                if dico.get(key):
                    raise Exception("'%s' is already use as a key for '%s'" % (key, dico[key]))
                print i('td')
                dico[key] = i('td')[1]
    return dico

def laws():
    for law_page in read_or_dl("http://www.lachambre.be/kvvcr/showpage.cfm?section=/flwb&language=fr&rightmenu=right&cfm=ListDocument.cfm", "all laws")('div', **{'class': re.compile("linklist_[01]")}):
        for soup in read_or_dl(LACHAMBRE_PREFIX + law_page.a["href"], "law %s" % law_page.a.text)('table')[4]('tr', valign="top"):
            get_or_create(Document, _id="lachambre_id", title=soup('div')[1].text, lachambre_id=soup.div.text, url=soup.a["href"])

    for law in list(Document.objects.all()):
        soup = read_or_dl(LACHAMBRE_PREFIX + law.url if not law.url.startswith("http") else law.url, "a law %s" % law.lachambre_id)
        law.full_details_url = soup('table')[4].a["href"]
        law.title = soup.h4.text
        # fucking stupid hack because BeautifulSoup fails to parse correctly the html
        soup = lxml_read_or_dl(LACHAMBRE_PREFIX + law.url if not law.url.startswith("http") else law.url, "a law %s" % law.lachambre_id)
        table = BeautifulSoup(etree.tostring(soup.xpath('//table')[4], pretty_print=True))
        dico = document_to_dico(list(table.table('tr', recursive=False)))
        handle_document(law, dico)
        law.save()

def handle_document(law, dico):
    if dico.get("Etat d'avancement"):
        law.status_chambre = clean_text(dico["Etat d'avancement"].contents[0])
        law.status_senat = clean_text(dico["Etat d'avancement"].contents[2]) if len(dico["Etat d'avancement"]) >= 3 else None

def run():
    clean()
    deputies()
    laws()
