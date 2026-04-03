# GGDDoc (Get from Git Design Documentation) 

GGDes is a documentation generator for a group of commits from git.
It gets as input a path to your git repository (local or remote), the source branch, and the 
target group of commits MR/PR that you want a design. Then a quick summary/context is requested,
followed by some simple questions about what is the documentation format(s) that the user needs, and
then it starts working.


# Architecture

## Output Format

In order to generate the documentation the anthropic skills for docx,pptx, pdf are being used with 
the respective python dependencies.

## Input 

It can be a path to a directory containing your git repository, or a gitlab/github link if login is
required GGDDoc will present the available auth options.

##  Internal Design


