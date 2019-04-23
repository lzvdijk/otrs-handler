"""
This script is a Python translation of contactmerge2.php, with the following
freely translated purpose.

1) Search OTRS for any tickets in queue 46, with subject:
    “Contactformulier KPN voor het IP adres [127.0.0.1]”
2) Check queues 9, 16 and 46 for tickets with subject:
    “Misbruik van uw internetaansluiting [127.0.0.1]”, with the same IP address.

Based on whether tickets are found or not, it then takes one of the following actions:
1) No ticket found -> Rename contact form, move to queue 9 and add IP address to relevant field.
2) 1 ticket found -> Merge tickets
3) Multiple tickets found -> Drop ticket (no action taken)

pip packages:

python-otrs
"""

import re
import ssl # this is only required for situations where ssl verification is broken
import structlog

# immediately initialise an error log
log = structlog.get_logger(__name__)

# access ticket elements as follows:
# testticket.find('Title').text
# or testticket.to_xml().find('Title').text

# command line argument support
from argparse import ArgumentParser

# ticket handling libs from python-otrs
try:
    from otrs.ticket.template import GenericTicketConnectorSOAP
    from otrs.client import GenericInterfaceClient
    from otrs.ticket.objects import Ticket, Article, DynamicField, Attachment
except ImportError as e:
    structlog.get_logger(log).error("Import error, please run pip install python-otrs: "+e)
    raise e

PARSER = ArgumentParser()

PARSER.add_argument("-u", "--user", dest="otrs_user", action="store",
                    type=str,
                    help='OTRS username',
                    metavar="")

PARSER.add_argument("-p", "--password", dest="otrs_pass", action="store",
                    type=str,
                    help='OTRS password',
                    metavar="")

PARSER.add_argument("-a", "--address", dest="otrs_url", action="store",
                    type=str,
                    help='OTRS root address',
                    metavar="")

PARSER.add_argument("-s", "--service", dest="otrs_soap_service", action="store",
                    type=str,
                    help='OTRS SOAP webservice name',
                    metavar="")

PARSER.add_argument("-v", "--verbose", dest="verbose", action="store_true",
                    help="print debug information during program execution")

args = PARSER.parse_args()

# could be simplified
otrs_user = args.otrs_user
otrs_pass = args.otrs_pass
otrs_url = args.otrs_url
otrs_soap_service = args.otrs_soap_service
verbose = args.verbose

def init_connection():
    """
    Returns a connected and authenticated OTRS client
    """

    # this is an evil evil way to 'fix' the lack of proper SSL certs in the internal otrs environment
    sslctx = ssl.create_default_context()
    sslctx.check_hostname = False
    sslctx.verify_mode = ssl.CERT_NONE

    # actually setup the client connection & register credentials
    otrsclient = GenericInterfaceClient(otrs_url, tc=GenericTicketConnectorSOAP(otrs_soap_service), ssl_context=sslctx)
    otrsclient.register_credentials(login=otrs_user, password=otrs_pass)

    return otrsclient

def update_ticket_queue(client, ticket_id, queue):
    """
    Update a ticket's queue id. Usually thisi d should be a single integer
    """
    if verbose:
        structlog.get_logger(log).info("Updating queue of ticket " + str(ticket_id) + " with '" + str(queue) + "'!")
    try:
        t_upd = Ticket(QueueIDs=[queue])
        client.tc.TicketUpdate(ticket_id, ticket=t_upd)
    except Exception as e:
        structlog.get_logger(log).error("Exception during queue update: "+e)

def update_ticket_ip(client, ticket_id, ip):
    """
    Update a ticket's ip address in the "CF-IP" free field according to abusedesk workflow.
    """
    if verbose:
        structlog.get_logger(log).info("Updating IP address of ticket " + str(ticket_id) + " with '" + str(ip) + "'!")
    try:
        t_upd = Ticket(DynamicField(Name='CF-IP', Value=ip))
        client.tc.TicketUpdate(ticket_id, ticket=t_upd)
    except Exception as e:
        structlog.get_logger(log).error("Exception during ip address update: "+e)

def close_ticket(client, ticket_id):
    """
    Update a ticket's state to 'Closed Succesful'.
    """
    if verbose:
        structlog.get_logger(log).info("Closing ticket " + str(ticket_id))
    try:
        t_upd = Ticket(State='resolved')
        client.tc.TicketUpdate(ticket_id, ticket=t_upd)
    except Exception as e:
        structlog.get_logger(log).error("Exception during ticket state update: "+e)

def open_ticket(client, ticket_id):
    """
    Update a ticket's state to 'Open'.
    """
    if verbose:
        structlog.get_logger(log).info("(Re)opening ticket " + str(ticket_id))
    try:
        t_upd = Ticket(State='Open')
        client.tc.TicketUpdate(ticket_id, ticket=t_upd)
    except Exception as e:
        structlog.get_logger(log).error("Exception during ticket state update: "+e)

def update_ticket_title(client, ticket_id, title):
    """
    Update the title of a ticket with a given value.

    Used to create a new primary dossier from an abuse ticket.
    """
    if verbose:
        structlog.get_logger(log).info("Updating title of ticket " + str(ticket_id) + " with title '" + str(title) + "'!")
    try:
        t_upd = Ticket(Title=title)
        client.tc.TicketUpdate(ticket_id, ticket=t_upd)
    except Exception as e:
        structlog.get_logger(log).error("Exception during title update: "+e)

def get_ticket_title_ip(client, ticketid):
    """
    Get the ip address from a ticket's title, based on ticket id.
    Grabs ip addresses from forms like "Contactformulier KPN voor het IP testadres [ip]"
    """
    if ticketid:
        try:
            ticket = get_ticket(client, ticketid).to_xml()
            extract = re.search(r'(\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3})', ticket.find('Title').text)
            if extract:
                ip = extract.group(1)
                if verbose:
                    structlog.get_logger(log).debug("Found ip address "+str(ip))
                return ip
            if verbose:
                structlog.get_logger(log).debug("No ip address found in given ticket")
        except Exception as e:
            raise e

    if verbose:
        structlog.get_logger(log).info("Invalid ticketID given!")

def get_ticket(client, ticketid):
    """
    Get a ticket from OTRS based on the OTRS ticket id (e.g. 34568)
    """
    if ticketid:
        try:
            ticket = client.tc.TicketGet(ticketid, get_articles=True, get_dynamic_fields=True, get_attachments=True)
        except Exception as e:
            raise e
        return ticket
    if verbose:
        structlog.get_logger(log).info("Invalid ticketID given!")

def merge_tickets(client, ticket1_id, ticket2_id):
    """
    Merges two tickets based on their ticket id's.

    Used to merge new abuse tickets into the ip's main dossier.
    """
    if verbose:
        structlog.get_logger(log).info("Merging tickets "+ str(ticket1_id) + " and " + str(ticket2_id))

    # get tickets
    ticket1 = get_ticket(client, ticket1_id)
    ticket2 = get_ticket(client, ticket2_id)

    if verbose:
        structlog.get_logger(log).debug("Title of merged ticket " + str(ticket1_id) + ": " + ticket1.to_xml().find('Title').text)
        structlog.get_logger(log).debug("Title of merged ticket " + str(ticket2_id) + ": " + ticket2.to_xml().find('Title').text)

    # add articles from ticket1 to ticket2
    ticket1_articles = ticket1.articles()
    for art in ticket1_articles:
        t_upd = ticket1_articles[ticket1_articles.index(art)]
        client.tc.TicketUpdate(ticket2_id, article=t_upd)

    # any information in free fields we want to add?

def primary_search(client, ip):
    """
    Search OTRS for any tickets in queue 25 with a certain subject
    """
    try:
        tickets = client.tc.TicketSearch(QueueIDs=[25], Title="%Contactformulier KPN voor het IP adres "+str(ip)+"%")
    except Exception as e:
        structlog.get_logger(log).error("Exception in primary search request: "+e)

    # return any results (empty set if none found)
    return tickets

def secondary_search(client, ip):
    """
    Search OTRS for any tickets in queues 22, 23 and 25 with a certain subject
    """
    try:
        tickets = client.tc.TicketSearch(QueueIDs=[22, 23, 25], Title="%Misbruik van uw internetverbinding "+"["+str(ip)+"]%")
    except Exception as e:
        structlog.get_logger(log).error("Exception in secondary search request: "+e)

    # return any results (empty set if none found)
    return tickets

def handle_results(client, primary_tickets, secondary_tickets, ip):
    """
    Helper function to process search results according to abusedesk workflow
    """

    # was a ticketid passed?
    if len(primary_tickets) > 0:
        # did the secondary search return any results?
        if len(secondary_tickets) > 0:
            # check for multiple dossiers
            if len(secondary_tickets) > 1:
                # if multiple dossiers are found, stop and log an error
                structlog.get_logger(log).error("Multiple dossiers found, aborting.")
                return
            else:
                # merge new tickets found into the main dossier and (re)open the dossier
                merge_tickets(client, primary_tickets[0], secondary_tickets[0])
                # close new ticket, (re)open main dossier
                close_ticket(client, primary_tickets[0])
                open_ticket(client, secondary_tickets[0])
        else:
            # new case, create a new dossier
            ticket_title = "Misbruik van uw internetverbinding "+"["+ip+"]"
            update_ticket_title(client, primary_tickets[0], ticket_title)
            #update_ticket_ip(client, primary_tickets[0], ip)
            update_ticket_queue(client, primary_tickets[0], 25)
            open_ticket(client, primary_tickets[0])

    else:
        if verbose:
            structlog.get_logger(log).info("No results found for ip: "+ip)

def main():
    """
    Basic main function for kicking off a search and processing the results.
    """

    # kick off a wildcard search for any tickets with the required titles first
    ip = "%"
    primary_tickets = []
    secondary_tickets = []

    try:
        # setup a connection to OTRS
        if verbose:
            structlog.get_logger(log).debug("Connecting to OTRS")

        client = init_connection()

        if verbose:
            structlog.get_logger(log).debug("Searching for ip: "+ip)

        # # kick off the OTRS searches
        primary_tickets = primary_search(client, ip)

        for ticket in primary_tickets:
            secondary_ip = get_ticket_title_ip(client, primary_tickets[primary_tickets.index(ticket)])
            secondary_tickets = secondary_search(client, secondary_ip)
            handle_results(client, [ticket], secondary_tickets, secondary_ip)

        if verbose:
            structlog.get_logger(log).debug("Primary search results: "+str(primary_tickets))
            structlog.get_logger(log).debug("Secondary search results: "+str(secondary_tickets))

    except ValueError as invalid_ip:
        structlog.get_logger(log).error("Invalid IP address found as input: "+invalid_ip)


if __name__ == "__main__":
    main()
