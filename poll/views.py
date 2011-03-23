from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_GET, require_POST
from django.template import RequestContext
from django.shortcuts import redirect, get_object_or_404, render_to_response
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.sites.models import Site
from django.contrib.auth.decorators import login_required, permission_required
from rapidsms_httprouter.router import get_router
from rapidsms.messages.outgoing import OutgoingMessage
from django.contrib.auth.models import Group
from .models import Poll, Category, Rule, Response, ResponseCategory, STARTSWITH_PATTERN_TEMPLATE, CONTAINS_PATTERN_TEMPLATE
from rapidsms.models import Contact
from simple_locations.models import Area
from rapidsms.models import Connection, Backend
from eav.models import Attribute

from .forms import *
from .models import ResponseForm, NameResponseForm, NumericResponseForm, LocationResponseForm

# CSV Export
@require_GET
def responses_as_csv(req, pk):
    poll = get_object_or_404(Poll, pk=pk)

    responses = poll.responses.all().order_by('-pk')

    resp = render_to_response(
        "polls/responses.csv", 
        {'responses': responses},
        mimetype="text/csv",
        context_instance=RequestContext(req))
    resp['Content-Disposition'] = 'attachment;filename="%s.csv"' % poll.name
    return resp

@require_GET
@login_required
def polls(req): 
    polls = Poll.objects.order_by('start_date')
    breadcrumbs = (('Polls', ''),)
    return render_to_response(
        "polls/poll_index.html", 
        { 'polls': polls, 'breadcrumbs': breadcrumbs },
        context_instance=RequestContext(req))

def demo(req, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    b1, created = Backend.objects.get_or_create(name="dmark")
    # Terra
    c1, created = Connection.objects.get_or_create(identity="256785137868", defaults={
        'backend':b1,
    })
    # Sharad
    b2, created = Backend.objects.get_or_create(name="utl")
    c2, created = Connection.objects.get_or_create(identity="256717171100", defaults={
        'backend':b2,
    })    
    router = get_router()
    outgoing = OutgoingMessage(c1, "dear Bulambuli representative: uReport, Uganda's community-level monitoring system, shows that 75% of young reporters in your district found that their local water point IS NOT functioning.")
    router.handle_outgoing(outgoing)
    outgoing = OutgoingMessage(c2, "dear Amuru representative: uReport, Uganda's community-level monitoring system, shows that 46.7% of young reporters in your district found that their local water point IS NOT functioning.")
    router.handle_outgoing(outgoing)
    return HttpResponse(status=200)

@permission_required('poll.can_poll')
def new_poll(req):
    if req.method == 'POST':
        form = NewPollForm(req.POST)
        form.updateTypes()
        if form.is_valid():
            # create our XForm
            question = form.cleaned_data['question']
            default_response = form.cleaned_data['default_response']
            contacts = form.cleaned_data['contacts']
            if hasattr(Contact, 'groups'):
                groups = form.cleaned_data['groups']
                contacts = Contact.objects.filter(Q(pk__in=contacts) | Q(groups__in=groups)).distinct()
            name = form.cleaned_data['name']
            if form.cleaned_data['type'] == Poll.TYPE_TEXT:
                poll = Poll.create_freeform(name, question, default_response, contacts, req.user)
            elif form.cleaned_data['type'] == Poll.TYPE_REGISTRATION:
                poll = Poll.create_registration(name, question, default_response, contacts, req.user)                
            elif form.cleaned_data['type'] == Poll.TYPE_NUMERIC:
                poll = Poll.create_numeric(name, question, default_response, contacts, req.user)
            elif form.cleaned_data['type'] == NewPollForm.TYPE_YES_NO:
                poll = Poll.create_yesno(name, question, default_response, contacts, req.user)
            elif form.cleaned_data['type'] == Poll.TYPE_LOCATION:
                poll = Poll.create_location_based(name, question, default_response, contacts, req.user)
            else:
                poll = Poll.create_custom(form.cleaned_data['type'], name, question, default_response, contacts, req.user)
            if settings.SITE_ID:
                poll.sites.add(Site.objects.get_current())
            poll.save()                
            if form.cleaned_data['start_immediately']:
                poll.start()
            return redirect("/polls/%d/view/" % poll.pk)
    else:
        form = NewPollForm()
        form.updateTypes()

    return render_to_response(
        "polls/poll_create.html", { 'form': form },
        context_instance=RequestContext(req))

@login_required
def view_poll(req, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    categories = Category.objects.filter(poll=poll)
    breadcrumbs = (('Polls', '/polls'),('Edit Poll', ''))
    return render_to_response("polls/poll_view.html", 
        { 'poll': poll, 'categories': categories, 'category_count' : len(categories), 'breadcrumbs' : breadcrumbs },
        context_instance=RequestContext(req))

@login_required
def view_report(req, poll_id, location_id=None, as_module=False):
    template = "polls/poll_report.html"
    poll = get_object_or_404(Poll, pk=poll_id)
    if location_id:
        locations = get_object_or_404(Area, pk=location_id).get_children().order_by('name')
    else:
        locations = Area.tree.root_nodes().order_by('name')
    
    if as_module:
        if poll.type == Poll.TYPE_TEXT:
            template = "polls/poll_report_text.html"
        elif poll.type == Poll.TYPE_NUMERIC:
            template = "polls/poll_report_numeric.html"
    
    breadcrumbs = (('Polls', '/polls'),)
    context = { 'poll':poll, 'breadcrumbs':breadcrumbs }
    context.update(poll.get_generic_report_data())
    report_rows = []
    for l in locations:
        if poll.type == Poll.TYPE_TEXT:
            report_row = poll.get_text_report_data(l)
            report_row['location'] = l
            report_rows.append(report_row)
        elif poll.type == Poll.TYPE_NUMERIC:
            report_row = poll.get_numeric_report_data(l)
            report_row['location'] = l
            report_rows.append(report_row)
    if not location_id:
        if poll.type == Poll.TYPE_TEXT:
            report_rows.append(poll.get_text_report_data())
        elif poll.type == Poll.TYPE_NUMERIC:
            report_rows.append(poll.get_numeric_report_data())
    context['report_rows'] = report_rows        
    
    if poll.type != Poll.TYPE_TEXT and poll.type != Poll.TYPE_NUMERIC:
        return render_to_response(
        "polls/poll_index.html",
        { 'polls': Poll.objects.order_by('start_date'), 'breadcrumbs': (('Polls', ''),) },
        context_instance=RequestContext(req))
    else:
        return render_to_response(template, context, context_instance=RequestContext(req))

@login_required
def view_poll_details(req, form_id):
    poll = get_object_or_404(Poll, pk=form_id)
    return render_to_response("polls/poll_details.html",
        { 'poll': poll },
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def edit_poll(req, poll_id):
    poll = get_object_or_404(Poll,pk=poll_id)
    categories = Category.objects.filter(poll=poll)

    breadcrumbs = (('Polls', '/polls'),('Edit Poll', ''))

    if req.method == 'POST':
        form = EditPollForm(req.POST, instance=poll)
        if form.is_valid():
            poll = form.save()
            poll.contacts = form.cleaned_data['contacts']
            return render_to_response("polls/poll_details.html", 
                {"poll" : poll},
                context_instance=RequestContext(req))
    else:
        form = EditPollForm(instance=poll)

    return render_to_response("polls/poll_edit.html", 
        { 'form': form, 'poll': poll, 'categories': categories, 'category_count' : len(categories), 'breadcrumbs' : breadcrumbs },
        context_instance=RequestContext(req))

@login_required
def view_responses(req, poll_id, as_module=False):
    poll = get_object_or_404(Poll,pk=poll_id)

    responses = poll.responses.all().order_by('-pk')

    breadcrumbs = (('Polls', '/polls'),('Responses', ''))
    
    template = "polls/responses.html"
    if as_module:
        template = "polls/response_table.html"

    typedef = Poll.TYPE_CHOICES[poll.type]
    return render_to_response(template,
        { 'poll': poll, 'responses': responses, 'breadcrumbs': breadcrumbs, 'columns': typedef['report_columns'], 'db_type': typedef['db_type'],'row_template':typedef['view_template']},
        context_instance=RequestContext(req))

def _get_response_edit_form(response, data=None):
    typedef = Poll.TYPE_CHOICES[response.poll.type]
    form = None
    if typedef['edit_form']:
        form = typedef['edit_form']
    else:
        parser = typedef['parser']
        class CustomForm(forms.Form):
            def __init__(self, data=None, **kwargs):
                response = kwargs.pop('response')
                if data:
                    forms.Form.__init__(self, data, **kwargs)
                else:
                    forms.Form.__init__(self, **kwargs)

            value = forms.CharField()
            def clean(self):
                cleaned_data = self.cleaned_data
                value = cleaned_data.get('value')
                try:
                    cleaned_data['value'] = parser(value)
                except ValidationError as e:
                    if getattr(e, 'messages', None):
                        self._errors['value'] = self.error_class([str(e.messages[0])])
                    else:
                        self._errors['value'] = self.error_class([u"Invalid value"])
                    del cleaned_data['value']
                return cleaned_data
        form = CustomForm

    if data:
        return form(data, response=response)
    else:
        value = None
        if not typedef['edit_form']:
            value = response.message.text
        elif typedef['db_type'] == Attribute.TYPE_TEXT:
            value = response.eav.poll_text_value
        elif typedef['db_type'] == Attribute.TYPE_FLOAT:
            value = response.eav.poll_number_value
        elif typedef['db_type'] == Attribute.TYPE_OBJECT:
            value = response.eav.poll_location_value
        return form(response=response, initial={'value':value})

@permission_required('poll.can_edit_poll')
def apply_response(req, response_id):
    response = get_object_or_404(Response, pk=response_id)
    poll = response.poll
    if poll.type == Poll.TYPE_REGISTRATION:
        try:
            response.message.connection.contact.name = response.eav.poll_text_value
            response.message.connection.contact.save()
        except AttributeError:
            pass
    elif poll.type == Poll.TYPE_LOCATION:
        try:
            response.message.connection.contact.reporting_location = response.eav.poll_location_value
            response.message.connection.contact.save()
        except AttributeError:
            pass

    return redirect("/polls/%d/responses/" % poll.pk)

@login_required
def apply_all(req, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    for response in Response.objects.filter(poll=poll):
        if poll.type == Poll.TYPE_REGISTRATION:
            try:
                response.message.connection.contact.name = response.eav.poll_text_value
                response.message.connection.contact.save()
            except AttributeError:
                pass
        elif poll.type == Poll.TYPE_LOCATION:
            try:
                response.message.connection.contact.reporting_location = response.eav.poll_location_value
                response.message.connection.contact.save()
            except AttributeError:
                pass
    return redirect("/polls/%d/responses/" % poll.pk)

@transaction.commit_on_success
@permission_required('poll.can_edit_poll')
def edit_response(req, response_id):
    response = get_object_or_404(Response, pk=response_id)
    poll = response.poll
    typedef = Poll.TYPE_CHOICES[poll.type]
    view_template = typedef['view_template']
    edit_template = typedef['edit_template']
    db_type = typedef['db_type']
    if req.method == 'POST':
        form = _get_response_edit_form(response, data=req.POST)
        if form.is_valid():
            if 'categories' in form.cleaned_data:
                response.update_categories(form.cleaned_data['categories'], req.user)

            if 'value' in form.cleaned_data:
                if db_type == Attribute.TYPE_FLOAT:
                    response.eav.poll_number_value = form.cleaned_data['value']
                elif db_type == Attribute.TYPE_OBJECT:
                    response.eav.poll_location_value = form.cleaned_data['value']
                elif db_type == Attibute.TYPE_TEXT:
                    response.eav.poll_text_value = form.cleaned_data['value']
            response.save()
            return render_to_response(view_template, 
                { 'response' : response, 'db_type':db_type },
                context_instance=RequestContext(req))
        else:
            return render_to_response(edit_template,
                            { 'response' : response, 'form':form, 'db_type':db_type },
                            context_instance=RequestContext(req))
    else:
        form = _get_response_edit_form(response)

    return render_to_response(edit_template,
        { 'form' : form, 'response': response, 'db_type':db_type },
        context_instance=RequestContext(req))

@login_required
def view_response(req, response_id):
    response = get_object_or_404(Response, pk=response_id)
    db_type = Poll.TYPE_CHOICES[response.poll.type]['db_type']
    view_template = Poll.TYPE_CHOICES[response.poll.type]['view_template']
    return render_to_response(view_template,
        { 'response': response, 'db_type': db_type},
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def delete_response (req, response_id):
    response = get_object_or_404(Response, pk=response_id)
    poll = response.poll
    if req.method == 'POST':
        response.delete()
        
    return redirect("/polls/%d/responses/" % poll.pk)

@login_required
def view_category(req, poll_id, category_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)
    return render_to_response("polls/category_view.html", 
        { 'poll': poll, 'category' : category },
        context_instance=RequestContext(req))

@transaction.commit_on_success
@permission_required('poll.can_edit_poll')
def edit_category (req, poll_id, category_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)
    if req.method == 'POST':
        form = CategoryForm(req.POST, instance=category)
        print form.errors
        if form.is_valid():
            if form.cleaned_data['default'] == True:
                Category.clear_defaults(poll)       
            category = form.save(commit=False)
            category.poll = poll
            category.save()
            return render_to_response("polls/category_view.html", 
                { 'form' : form, 'poll': poll, 'category' : category },
                context_instance=RequestContext(req))
        else:
            return render_to_response("polls/category_edit.html", 
                            { 'form' : form, 'poll': poll, 'category' : category },
                            context_instance=RequestContext(req))
    else:
        form = CategoryForm(instance=category)

    return render_to_response("polls/category_edit.html", 
        { 'form' : form, 'poll': poll, 'category' : category },
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def add_category(req, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    form = CategoryForm()

    if req.method == 'POST':
        form = CategoryForm(req.POST)
        if form.is_valid():
            if form.cleaned_data['default'] == True:
                for c in Category.objects.filter(poll=poll, default=True):
                    c.default=False
                    c.save()
            category = form.save(commit=False)
            category.poll = poll
            category.save()
            poll.categories.add(category)
            return render_to_response("polls/category_view.html", 
                { 'category' : category, 'form' : form, 'poll' : poll },
                context_instance=RequestContext(req))
    else:
        form = CategoryForm()

    return render_to_response("polls/category_edit.html", 
        { 'form' : form, 'poll' : poll },
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def delete_poll (req, poll_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if req.method == 'POST':
        poll.delete()
        
    return redirect("/polls")

@permission_required('poll.can_poll')
def start_poll (req, poll_id):
    poll = Poll.objects.get(pk=poll_id)
    if req.method == 'POST':
        poll.start()
        
    return render_to_response("polls/poll_details.html", 
        {"poll" : poll},
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def end_poll (req, poll_id):
    poll = Poll.objects.get(pk=poll_id)
    if req.method == 'POST':
        poll.end()
        
    return render_to_response("polls/poll_details.html", 
        {"poll" : poll},
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def delete_category (req, poll_id, category_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)

    if req.method == 'POST':
        category.delete()
        
    return redirect("/polls/%d/edit/" % poll.pk)

@permission_required('poll.can_edit_poll')
def edit_rule(req, poll_id, category_id, rule_id) :
    
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)
    rule = get_object_or_404(Rule, pk=rule_id)
    
    if req.method == 'POST':
        form = RuleForm(req.POST, instance=rule)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.update_regex()
            rule.save()
            poll.reprocess_responses()
            return render_to_response("polls/table_row_view.html", 
                {  'columns' : rule_columns, 'buttons' : rule_buttons, 'item' : rule, 'form' : form, 'poll' : poll, 'category' : category },
                context_instance=RequestContext(req))
        else:
            return render_to_response("polls/table_row_edit.html", 
                { 'buttons' : save_button, 'item' : rule, 'form' : form, 'poll' : poll, 'category' : category },
                context_instance=RequestContext(req))
    else:
        form = RuleForm(instance=rule)
    
    return render_to_response("polls/table_row_edit.html", 
        { 'buttons' : save_button, 'form' : form, 'poll': poll, 'category' : category, 'item' : rule },
        context_instance=RequestContext(req))

@permission_required('poll.can_edit_poll')
def add_rule(req, poll_id, category_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    if poll.type != Poll.TYPE_TEXT:
        return HttpResponse(status=404)
    category = get_object_or_404(Category, pk=category_id)
    form = RuleForm()

    if req.method == 'POST':
        form = RuleForm(req.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.category = category
            rule.update_regex()
            rule.save()
            poll.reprocess_responses()
            return render_to_response("polls/table_row_view.html", 
                {  'columns' : rule_columns, 'buttons' : rule_buttons, 'item' : rule, 'form' : form, 'poll' : poll, 'category' : category },
                context_instance=RequestContext(req))
    else:
        form = RuleForm()

    return render_to_response("polls/table_row_edit.html", 
        { 'buttons' : save_button, 'form' : form, 'poll': poll, 'category' : category },
        context_instance=RequestContext(req))

@login_required
def view_rule(req, poll_id, category_id, rule_id) :
    
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)
    rule = get_object_or_404(Rule, pk=rule_id)
    return render_to_response("polls/table_row_view.html", 
        { 'columns' : rule_columns, 'buttons' : rule_buttons, 'item' : rule, 'poll' : poll, 'category' : category },
        context_instance=RequestContext(req))
    
@login_required
def view_rules(req, poll_id, category_id):
    poll = get_object_or_404(Poll, pk=poll_id)
    category = get_object_or_404(Category, pk=category_id)
    rules = Rule.objects.filter(category=category)

    breadcrumbs = (('Polls', '/polls'),(poll.name, "/polls/%s/view/" % poll.pk), ("Categories", ''))

    return render_to_response("polls/rules.html", 
        {  'poll' : poll, 'category' : category, 'table' : rules, 'buttons' : rule_buttons, 'columns' : rule_columns, 'breadcrumbs': breadcrumbs },
        context_instance=RequestContext(req))

@transaction.commit_on_success
@permission_required('poll.can_edit_poll')
def delete_rule (req, poll_id, category_id, rule_id):
    rule = get_object_or_404(Rule, pk=rule_id)
    category = rule.category
    if req.method == 'POST':
        rule.delete()
    category.poll.reprocess_responses()
    return redirect("/polls/%s/category/%s/rules/" % (poll_id, category_id))

add_button = ({ "image" : "rapidsms/icons/silk/decline.png", 'click' : 'cancelAdd'}, 
              { "text" : "Add", "image" : "rapidsms/icons/silk/add.png" , 'click' : 'add'},)

save_button = ( { "image" : "rapidsms/icons/silk/decline.png", 'click' : 'cancelSave'},
                { "text" : "Save", "image" : "poll/icons/silk/bullet_disk.png", 'click' : 'saveRow'},)
rule_buttons = ({"image" : "rapidsms/icons/silk/delete.png", 'click' : 'deleteRow'},
                      { "text" : "Edit", "image" : "poll/icons/silk/pencil.png", 'click' : 'editRow'},)

rule_columns = (('Rule', 'rule_type_friendly'), ('Text', 'rule_string'))

